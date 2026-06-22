/**
 * Wires spec.identity_providers + the current asker into the `ctx.identity`
 * resolver tools call. Resolution keys off the asker's AgentUser id — so a
 * credential is only ever "act as THIS asker", never the session owner's.
 */

import type { IdentityStore } from '../persistence/identity-store'
import type { IdentityProviderConfig, SessionPrincipal } from '../spec/spec'
import type { IdentityResolution } from '../spec/tool'
import type { HttpFetcher } from './http-client'
import type { IdentityCredentialStore } from './identity-credential-store'
import type { IdentityLinkStateStore } from './identity-link-state-store'
import { type IdentityProvider, type IdentityProviderRegistry, MapIdentityProviderRegistry } from './identity-provider'
import { Oauth2AuthProvider } from './oauth2-identity-provider'
import { PostHogAuthProvider } from './posthog-identity-provider'

export interface BuildIdentityRegistryDeps {
    links: IdentityLinkStateStore
    credentials: IdentityCredentialStore
    http: HttpFetcher
    /** Resolve an encrypted_env secret by name (for oauth2 client_secret_ref). */
    secret: (name: string) => string | undefined
    /**
     * PostHog instance base URL (no trailing slash). When set, a `{kind:posthog}`
     * provider is built against `${base}/oauth/{authorize,token,userinfo}/` using
     * the client_id Django provisioned into the spec. Omit it (or omit the
     * client_id) and posthog providers are skipped — they can't link.
     */
    posthogBaseUrl?: string
}

/** Build the per-revision provider registry from spec.identity_providers. */
export function buildIdentityRegistry(
    configs: readonly IdentityProviderConfig[],
    deps: BuildIdentityRegistryDeps
): IdentityProviderRegistry {
    const providers: IdentityProvider[] = []
    for (const cfg of configs) {
        if (cfg.kind === 'oauth2') {
            providers.push(
                new Oauth2AuthProvider({
                    config: {
                        id: cfg.id,
                        authorizeUrl: cfg.authorize_url,
                        tokenUrl: cfg.token_url,
                        clientId: cfg.client_id,
                        clientSecret: cfg.client_secret_ref ? deps.secret(cfg.client_secret_ref) : undefined,
                        scopes: cfg.scopes,
                        userinfoUrl: cfg.userinfo_url,
                    },
                    links: deps.links,
                    credentials: deps.credentials,
                    http: deps.http,
                })
            )
        } else if (cfg.kind === 'posthog' && deps.posthogBaseUrl && cfg.client_id) {
            const base = deps.posthogBaseUrl.replace(/\/+$/, '')
            providers.push(
                new PostHogAuthProvider({
                    config: {
                        id: cfg.id,
                        authorizeUrl: `${base}/oauth/authorize/`,
                        tokenUrl: `${base}/oauth/token/`,
                        userinfoUrl: `${base}/oauth/userinfo/`,
                        clientId: cfg.client_id,
                        scopes: cfg.scopes,
                    },
                    links: deps.links,
                    credentials: deps.credentials,
                    http: deps.http,
                })
            )
        }
    }
    return new MapIdentityProviderRegistry(providers)
}

/**
 * The AgentUser id a principal links credentials under. Slack carries it
 * directly; jwt/posthog map through the identity store. Anonymous/service
 * principals aren't linkable (return null → resolve() reports unavailable).
 */
export async function agentUserIdForPrincipal(
    principal: SessionPrincipal | null,
    deps: { identities?: IdentityStore; applicationId: string; teamId: number }
): Promise<string | null> {
    if (!principal) {
        return null
    }
    const findOrCreate = async (kind: string, id: string): Promise<string | null> => {
        if (!deps.identities) {
            return null
        }
        const u = await deps.identities.findOrCreate({
            team_id: deps.teamId,
            application_id: deps.applicationId,
            principal_kind: kind,
            principal_id: id,
        })
        return u.id
    }
    switch (principal.kind) {
        case 'slack':
            return principal.agent_user_id ?? null
        case 'jwt':
            return findOrCreate('jwt', principal.sub)
        case 'posthog':
            return findOrCreate('posthog', principal.user_id)
        default:
            return null
    }
}

export interface ToolIdentityDeps {
    registry: IdentityProviderRegistry
    agentUserId: string | null
    teamId: number
    applicationId: string
    /** Our OAuth callback URL for a provider. */
    redirectUriFor: (providerId: string) => string
    /**
     * When set, identity is refused with this reason. Used to fail closed in
     * shared participant threads where the asker isn't the session owner —
     * resolving the owner's credential for someone else would be a confused
     * deputy (T1), so we don't resolve at all there.
     */
    unavailableReason?: string
}

export function createToolIdentity(deps: ToolIdentityDeps): {
    resolve(provider: string, scopes?: string[]): Promise<IdentityResolution>
} {
    return {
        async resolve(providerId, scopes = []): Promise<IdentityResolution> {
            if (deps.unavailableReason) {
                return { kind: 'unavailable', provider: providerId, reason: deps.unavailableReason }
            }
            const provider = deps.registry.get(providerId)
            if (!provider) {
                return { kind: 'unavailable', provider: providerId, reason: 'unknown_provider' }
            }
            if (!deps.agentUserId) {
                return { kind: 'unavailable', provider: providerId, reason: 'principal_not_linkable' }
            }
            const args = {
                agentUserId: deps.agentUserId,
                teamId: deps.teamId,
                applicationId: deps.applicationId,
                scopes,
            }
            const credential = await provider.resolve(args)
            if (credential) {
                return { kind: 'ok', credential, allowedHosts: provider.allowedHosts() }
            }
            const { authorizeUrl } = await provider.initiate({ ...args, redirectUri: deps.redirectUriFor(providerId) })
            return { kind: 'link_required', provider: providerId, authorizeUrl }
        },
    }
}
