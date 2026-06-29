/**
 * Wires spec.identity_providers + the current asker into the `ctx.identity`
 * resolver tools call. Resolution keys off the asker's AgentUser id — so a
 * credential is only ever "act as THIS asker", never the session owner's.
 */

import type { IdentityStore } from '../persistence/identity-store'
import type { AgentRevision, AgentSession, IdentityProviderConfig, SessionPrincipal } from '../spec/spec'
import type { IdentityResolution, ToolContext } from '../spec/tool'
import type { Credential, CredentialBroker } from './credential-broker'
import type { HttpFetcher } from './http-client'
import type { IdentityCredentialStore } from './identity-credential-store'
import type { IdentityLinkStateStore } from './identity-link-state-store'
import { type IdentityProvider, type IdentityProviderRegistry, MapIdentityProviderRegistry } from './identity-provider'
import { Oauth2AuthProvider } from './oauth2-identity-provider'
import { PostHogAuthProvider, SeedOnlyPostHogProvider } from './posthog-identity-provider'

/** Structured logger shape `createToolIdentity`/`buildAskerIdentity` use for the
 *  `identity.resolved` session-log line. Matches the runner's `log` closure. */
export type IdentityLog = (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void

/**
 * Thrown by a tool (or its credential helper) when the asker hasn't linked a
 * required identity provider and a link must be relayed. The native-tool
 * dispatch wrapper catches it and converts it to a uniform `auth_required`
 * tool result — the model relays the link rather than treating it as an error.
 * Carried in `@posthog/agent-shared` so both tools (which throw it) and the
 * runner (which catches it) share one type.
 */
export class IdentityAuthRequiredError extends Error {
    constructor(
        readonly provider: string,
        readonly authorizeUrl: string
    ) {
        super(`identity_link_required: ${provider}`)
        this.name = 'IdentityAuthRequiredError'
    }
}

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
                        binding: cfg.binding,
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
                        binding: cfg.binding,
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
     * shared participant threads (`allow_workspace_participants`): there we
     * can't trust that the asker is the session owner, and resolving the
     * owner's credential for any other participant would be a confused deputy
     * (T1) — so we refuse for EVERY asker in the thread (the owner included),
     * not just when asker ≠ owner. Fail closed for the whole thread.
     */
    unavailableReason?: string
    /**
     * Trigger-edge credential source — the per-session broker, narrowed to a
     * single `resolve(target)`. Consulted (by `provider.credentialTarget`)
     * BEFORE the persistent linked store: this is the PostHog Code passthrough
     * (a `posthog` principal's bearer seeded at /run) and any other auth that
     * was established at the trigger edge rather than via an OAuth link.
     */
    seed?: { resolve(target: string): Promise<Credential | null> }
    /** Emits the `identity.resolved` session-log line on every resolve. */
    log?: IdentityLog
}

export function createToolIdentity(deps: ToolIdentityDeps): {
    resolve(provider: string, scopes?: string[]): Promise<IdentityResolution>
    relink(provider: string): Promise<string | null>
} {
    return {
        /**
         * Force a fresh authorize link for an ALREADY-linked provider — the
         * reconnect path. A consumer that resolved `ok` but had the credential
         * rejected downstream (e.g. an MCP server reports the grant is missing a
         * scope, or the token was revoked) calls this to relay a re-authorize
         * link instead of dead-ending as "unavailable". Returns null when no link
         * is possible (shared session, unlinkable principal, or a seed-only
         * provider with no OAuth app) — the caller then keeps the plain failure.
         */
        async relink(providerId): Promise<string | null> {
            if (deps.unavailableReason || !deps.agentUserId) {
                return null
            }
            const provider = deps.registry.get(providerId)
            if (!provider) {
                return null
            }
            try {
                const { authorizeUrl } = await provider.initiate({
                    agentUserId: deps.agentUserId,
                    teamId: deps.teamId,
                    applicationId: deps.applicationId,
                    scopes: [],
                    redirectUri: deps.redirectUriFor(providerId),
                })
                deps.log?.('info', 'identity.relink', { provider: providerId, agent_user_id: deps.agentUserId })
                return authorizeUrl
            } catch (err) {
                deps.log?.('warn', 'identity.relink_unavailable', {
                    provider: providerId,
                    reason: (err as Error).message,
                })
                return null
            }
        },
        async resolve(providerId, scopes = []): Promise<IdentityResolution> {
            // One session-log line per resolution: the credential source + decision, never the token.
            const emit = (res: IdentityResolution, source: string, binding?: string): IdentityResolution => {
                deps.log?.('info', 'identity.resolved', {
                    provider: providerId,
                    source,
                    binding,
                    reason: res.kind === 'unavailable' ? res.reason : undefined,
                    agent_user_id: deps.agentUserId ?? undefined,
                    shared_session: deps.unavailableReason ? true : undefined,
                })
                return res
            }

            // Shared-session gate FIRST — the seed must never resolve the owner's
            // edge bearer for a different asker (confused deputy, T1).
            if (deps.unavailableReason) {
                return emit(
                    { kind: 'unavailable', provider: providerId, reason: deps.unavailableReason },
                    'unavailable'
                )
            }
            const provider = deps.registry.get(providerId)
            if (!provider) {
                return emit({ kind: 'unavailable', provider: providerId, reason: 'unknown_provider' }, 'unavailable')
            }
            // Trigger-edge seed (PostHog Code passthrough), keyed by target.
            if (deps.seed) {
                const seeded = await deps.seed.resolve(provider.credentialTarget)
                if (seeded) {
                    return emit(
                        { kind: 'ok', credential: seeded, allowedHosts: provider.allowedHosts() },
                        'edge_seed',
                        provider.binding
                    )
                }
            }
            // No seed and not linkable (anonymous/service principal).
            if (!deps.agentUserId) {
                return emit(
                    { kind: 'unavailable', provider: providerId, reason: 'principal_not_linkable' },
                    'unavailable',
                    provider.binding
                )
            }
            const args = {
                agentUserId: deps.agentUserId,
                teamId: deps.teamId,
                applicationId: deps.applicationId,
                scopes,
            }
            // Linked credential, else initiate a link. Wrapped so a non-linkable
            // provider, the unimplemented `agent` binding, or a refresh failure
            // degrade to `unavailable` instead of crashing dispatch.
            try {
                const credential = await provider.resolve(args)
                if (credential) {
                    return emit(
                        { kind: 'ok', credential, allowedHosts: provider.allowedHosts() },
                        'linked_store',
                        provider.binding
                    )
                }
                const { authorizeUrl } = await provider.initiate({
                    ...args,
                    redirectUri: deps.redirectUriFor(providerId),
                })
                return emit(
                    { kind: 'link_required', provider: providerId, authorizeUrl },
                    'link_required',
                    provider.binding
                )
            } catch (err) {
                return emit(
                    { kind: 'unavailable', provider: providerId, reason: (err as Error).message },
                    'unavailable',
                    provider.binding
                )
            }
        },
    }
}

export interface BuildAskerIdentityDeps {
    credentials: IdentityCredentialStore
    links: IdentityLinkStateStore
    /** Resolves a non-slack principal to its AgentUser id for linking. */
    identities?: IdentityStore
    /** Per-session broker — the trigger-edge seed source. */
    credentialBroker?: CredentialBroker
    http: HttpFetcher
    /** Resolve an encrypted_env secret by name (oauth2 client_secret_ref). */
    secret: (name: string) => string | undefined
    /** PostHog instance base URL — builds the managed posthog provider + the
     *  implicit seed-only fallback. */
    posthogApiBaseUrl: string
    /** OAuth callback base; `/link/<provider>/callback` is appended. */
    linkRedirectBaseUrl?: string
    log?: IdentityLog
}

/**
 * Build the run's per-asker `ctx.identity` resolver — the ONE seam both the
 * driver (native/custom tool credential resolution) and the worker (MCP
 * `auth.provider`) use, so they resolve identically (same shared-session gate,
 * same edge-seed wiring).
 *
 * Always registers an implicit seed-only PostHog provider when no
 * `{kind:posthog}` provider is declared, so a PostHog Code session resolves the
 * trigger-edge bearer for `posthog` without the agent having to declare/provision
 * an OAuthApplication it never links against.
 */
export async function buildAskerIdentity(
    rev: AgentRevision,
    session: AgentSession,
    deps: BuildAskerIdentityDeps
): Promise<ToolContext['identity']> {
    const baseRegistry = buildIdentityRegistry(rev.spec.identity_providers, {
        links: deps.links,
        credentials: deps.credentials,
        http: deps.http,
        secret: deps.secret,
        posthogBaseUrl: deps.posthogApiBaseUrl,
    })
    const providers = baseRegistry.all()
    const hasPosthogTarget = providers.some((p) => p.credentialTarget === 'posthog_api')
    const registry =
        hasPosthogTarget || !deps.posthogApiBaseUrl
            ? baseRegistry
            : new MapIdentityProviderRegistry([
                  ...providers,
                  new SeedOnlyPostHogProvider('posthog', deps.posthogApiBaseUrl),
              ])

    const slackTrigger = rev.spec.triggers.find((t) => t.type === 'slack')
    const sharedSession = slackTrigger?.type === 'slack' && slackTrigger.config.allow_workspace_participants
    const agentUserId = await agentUserIdForPrincipal(session.principal, {
        identities: deps.identities,
        applicationId: rev.application_id,
        teamId: session.team_id,
    })
    const base = deps.linkRedirectBaseUrl ?? 'https://agents.posthog.com'
    return createToolIdentity({
        registry,
        agentUserId,
        teamId: session.team_id,
        applicationId: rev.application_id,
        redirectUriFor: (p) => `${base}/link/${p}/callback`,
        unavailableReason: sharedSession ? 'shared_session_unsupported' : undefined,
        seed: deps.credentialBroker ? { resolve: (t) => deps.credentialBroker!.resolve(session.id, t) } : undefined,
        log: deps.log,
    })
}
