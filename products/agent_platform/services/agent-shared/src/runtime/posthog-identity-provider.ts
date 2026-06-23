/**
 * Managed PostHog identity provider. PostHog's own OAuth2 surface
 * (/oauth/authorize, /oauth/token, /oauth/userinfo) is standard auth-code +
 * PKCE, so this is just the generic `Oauth2AuthProvider` with three additions:
 *
 *   1. `establishesIdentity = true` — linking proves WHO the principal is.
 *   2. `deriveSubject` reads /oauth/userinfo `sub` (the PostHog user uuid) so
 *      `complete()` stamps it on the stored credential. Per-asker auth then
 *      resolves the PostHog user behind a Slack principal from that subject.
 *   3. `credentialTarget = 'posthog_api'` — the broker key the native
 *      `@posthog/*` tools resolve under, and the key `createToolIdentity`
 *      consults for the trigger-edge seed (PostHog Code passthrough). The
 *      linked-credential store stays keyed by the provider `id` (default
 *      `posthog`); both axes resolve to the same logical PostHog bearer.
 *
 * The OAuthApplication backing this is provisioned per-agent by Django on
 * promote (a normal, user-consented app — not first-party); its client_id is
 * injected into the frozen spec and threaded in as `config.clientId`.
 */

import type { Credential } from './credential-broker'
import type {
    IdentityCompleteInput,
    IdentityCompleteResult,
    IdentityInitiateInput,
    IdentityInitiateResult,
    IdentityProvider,
    IdentityResolveInput,
} from './identity-provider'
import { Oauth2AuthProvider } from './oauth2-identity-provider'

export class PostHogAuthProvider extends Oauth2AuthProvider {
    override readonly establishesIdentity = true

    // The edge seed (PostHog Code's posthog bearer) and the native `@posthog/*`
    // tools both key off `posthog_api`; the linked store stays keyed by `id`.
    override get credentialTarget(): string {
        return 'posthog_api'
    }

    protected override async deriveSubject(accessToken: string): Promise<string | undefined> {
        const url = this.deps.config.userinfoUrl
        if (!url) {
            return undefined
        }
        // Best-effort: a userinfo hiccup must not block the link succeeding as a
        // capability. Without a subject the credential just isn't identity-bearing.
        try {
            const res = await this.deps.http.fetch(url, {
                method: 'GET',
                headers: { Authorization: `Bearer ${accessToken}`, Accept: 'application/json' },
            })
            if (!res.ok) {
                return undefined
            }
            const json = (await res.json()) as { sub?: string }
            return typeof json.sub === 'string' && json.sub.length > 0 ? json.sub : undefined
        } catch {
            return undefined
        }
    }
}

/**
 * Surfaces the trigger-edge PostHog bearer (PostHog Code passthrough) but can't
 * link. Registered implicitly when no `{kind:posthog}` provider is declared, so a
 * posthog-principal session resolves `posthog` without provisioning an
 * OAuthApplication. With no seed and no link, `resolve()` is null and `initiate()`
 * refuses — so a non-posthog asker resolves to `unavailable`, not a dead link.
 */
export class SeedOnlyPostHogProvider implements IdentityProvider {
    readonly establishesIdentity = false
    readonly binding = 'principal' as const
    private readonly host: string

    constructor(
        readonly id: string,
        posthogApiBaseUrl: string
    ) {
        this.host = new URL(posthogApiBaseUrl).host
    }

    get credentialTarget(): string {
        return 'posthog_api'
    }

    allowedHosts(): string[] {
        return [this.host]
    }

    async initiate(_input: IdentityInitiateInput): Promise<IdentityInitiateResult> {
        throw new Error('link_unavailable_no_oauth_app')
    }

    async complete(_input: IdentityCompleteInput): Promise<IdentityCompleteResult> {
        throw new Error('link_unavailable_no_oauth_app')
    }

    async resolve(_input: IdentityResolveInput): Promise<Credential | null> {
        return null
    }
}
