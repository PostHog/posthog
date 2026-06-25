/**
 * Credential broker — Pattern B: the
 * `SessionPrincipal` carries identity only; **tokens never land on the
 * session row or principal.** The verifier at /run + /send produces a
 * credential map alongside the principal; that map gets written here,
 * keyed by `session_id`. Tools call `broker.resolve(session_id, target)`
 * at call time to get whatever auth they need.
 *
 * Targets are conventions, not platform constants. Spec authors decide
 * what targets their tools ask for. Conventions in use today:
 *
 *   - `posthog_api` — bearer for calling `app.posthog.com/api/*`
 *     (set by `oauth` + `pat` modes)
 *   - `self`       — the raw auth proof + decoded claims
 *     (set by `jwt` mode — agent-author-defined semantics)
 *
 * Lifecycle:
 *
 *   - Written at /run + /send by ingress (so a fresh token re-supplied
 *     by the client on /send overwrites any earlier one)
 *   - Read by the runner's tool dispatch path
 *   - Auto-expired by the impl (TTL set per write); the in-memory impl
 *     drops entries on `clear(session_id)` when the session ends, the
 *     Redis impl will lean on TTL
 *
 * Worker restart loses the in-memory cache → next tool call resolves to
 * `null` → tool returns an error → the user's next /send refreshes the
 * broker. Same lifecycle as the client-tool dispatcher.
 */

export type Credential =
    /**
     * PostHog credential bearer (PAT today, OAuth later), usable as
     * `Authorization: Bearer <token>`. Available to tools under `posthog_api`.
     */
    | { kind: 'posthog_bearer'; token: string; scopes?: string[]; expires_at?: number }
    /**
     * Generic OAuth2 bearer from a linked third-party identity provider
     * (GitHub, Linear, the `dogs` test IdP, …). Usable as
     * `Authorization: Bearer <token>`; `provider` records which IdP issued it.
     * Resolved per-principal from the linked-credential store, not a team
     * integration — this is "act as THIS user on that service".
     */
    | { kind: 'oauth_bearer'; token: string; provider: string; scopes?: string[]; expires_at?: number }
    /**
     * Raw JWT + its decoded claims. The platform doesn't know how the
     * agent author intends to use this — tools either re-send the JWT
     * (e.g. to call back into the issuing system) or read `claims`.
     */
    | { kind: 'jwt'; token: string; claims: Record<string, unknown> }

/**
 * Map of target → credential. Targets are author-defined strings; the
 * verifier populates this with whatever auth materials it has on hand.
 */
export type CredentialMap = Record<string, Credential>

export interface CredentialBroker {
    /**
     * Write the credential map for a session. Overwrites any prior
     * entry (so /send can refresh creds mid-session). TTL governs
     * automatic expiry on the implementation side; default = 24h.
     */
    write(sessionId: string, credentials: CredentialMap, opts?: { ttlMs?: number }): Promise<void>
    /**
     * Resolve a credential for `(session, target)`. Returns null when
     * the session has no creds, the target isn't bound, or the entry
     * has expired.
     */
    resolve(sessionId: string, target: string): Promise<Credential | null>
    /**
     * Drop a session's creds explicitly. Called by the runner at
     * session end; impls may also drop on TTL.
     */
    clear(sessionId: string): Promise<void>
}

export const DEFAULT_CREDENTIAL_TTL_MS = 24 * 60 * 60 * 1000

interface MemoryEntry {
    credentials: CredentialMap
    expires_at: number
}

/**
 * In-process broker — the harness + dev default. Single-worker only;
 * cross-process deployments need the Redis impl.
 */
export class MemoryCredentialBroker implements CredentialBroker {
    private readonly entries = new Map<string, MemoryEntry>()

    async write(sessionId: string, credentials: CredentialMap, opts: { ttlMs?: number } = {}): Promise<void> {
        const ttlMs = opts.ttlMs ?? DEFAULT_CREDENTIAL_TTL_MS
        this.entries.set(sessionId, { credentials, expires_at: Date.now() + ttlMs })
    }

    async resolve(sessionId: string, target: string): Promise<Credential | null> {
        const entry = this.entries.get(sessionId)
        if (!entry) {
            return null
        }
        if (entry.expires_at <= Date.now()) {
            this.entries.delete(sessionId)
            return null
        }
        return entry.credentials[target] ?? null
    }

    async clear(sessionId: string): Promise<void> {
        this.entries.delete(sessionId)
    }
}
