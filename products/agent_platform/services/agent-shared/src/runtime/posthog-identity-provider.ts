/**
 * Managed PostHog identity provider. PostHog's own OAuth2 surface
 * (/oauth/authorize, /oauth/token, /oauth/userinfo) is standard auth-code +
 * PKCE, so this is just the generic `Oauth2AuthProvider` with two additions:
 *
 *   1. `establishesIdentity = true` — linking proves WHO the principal is.
 *   2. `deriveSubject` reads /oauth/userinfo `sub` (the PostHog user uuid) so
 *      `complete()` stamps it on the stored credential. Per-asker auth then
 *      resolves the PostHog user behind a Slack principal from that subject.
 *
 * The OAuthApplication backing this is provisioned per-agent by Django on
 * promote (a normal, user-consented app — not first-party); its client_id is
 * injected into the frozen spec and threaded in as `config.clientId`.
 */

import { Oauth2AuthProvider } from './oauth2-identity-provider'

export class PostHogAuthProvider extends Oauth2AuthProvider {
    override readonly establishesIdentity = true

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
