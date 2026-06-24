/**
 * Map an inbound request to an AgentApplication + a revision.
 *
 * Live invokes never carry revision info; the resolver looks up the
 * application's `live_revision_id`.
 *
 * Non-live ("preview") invokes carry the revision-id-hex as part of the URL
 * (NOT as a query param or header — those were dropped in favor of a single
 * URL-only contract):
 *
 *   - "domain" (prod): `<rev-hex-prefix>.<slug>.agents.posthog.com`
 *     For example `019e6f25.weekly-digest.agents.posthog.com`.
 *   - "path"   (dev) : `/agents/<slug>-<rev-hex-prefix>/...`
 *     For example `/agents/weekly-digest-019e6f25/run`.
 *
 * The prefix can be 8–32 hex chars (no dashes). 32 = the full UUID with
 * dashes stripped, which is what the Django preview-proxy uses for
 * unambiguous addressing. 8 is the ergonomic short form for human-shared
 * URLs.
 */

import {
    AgentApplication,
    AgentRevision,
    INTERNAL_JWT_AUDIENCE,
    InternalJwtVerifyError,
    RevisionStore,
    verifyInternalJwt,
} from '@posthog/agent-shared'

export type RoutingMode = 'domain' | 'path'

export interface ResolvedAgent {
    application: AgentApplication
    revision: AgentRevision
    /**
     * True when this is a "preview" (better: MOCKED) run — the runner
     * suppresses real-world side effects (Slack writes, webhook delivery,
     * write-side MCP/custom tools) and tags `$ai_*` events so author
     * iteration stays out of prod observability. Two ways to land here, both
     * decided by `assertPreviewGate` before this is set:
     *   1. The resolved revision is NOT the application's `live_revision_id`
     *      (a draft/ready revision). These ALWAYS require a valid preview JWT
     *      — running unpublished code anonymously would be a hole.
     *   2. The resolved revision IS live, but the request carried a valid
     *      `aud=agent-ingress.preview` JWT. The live spec is already public,
     *      so mocking it exposes nothing new — this is the "safely test /
     *      reproduce the live agent without firing real side effects" path.
     *
     * NB the name is a misnomer kept for wire/schema compatibility: it does
     * NOT mean "a draft" — it means "side effects are mocked." See
     * `agent_session.is_preview` and `docs/preview-mode.md`. Triggers forward
     * this to `enqueueOrResume` as `isPreview` so it lands on
     * `agent_session.is_preview`.
     */
    isPreview: boolean
    /**
     * Unix-seconds expiry of the preview JWT that authorized this
     * resolution, or null on live requests / dev paths without a signing
     * key. The chat `/listen` SSE handler schedules a
     * `preview_token_required` event at this timestamp so a long-lived
     * stream (15-min TTL token, multi-hour author session) closes with a
     * specific auth-recovery signal the UI can act on, instead of an
     * opaque connection drop. Only populated for preview resolutions —
     * live revisions have nothing to expire.
     */
    previewJwtExp: number | null
}

/**
 * Thrown by the resolver when a `<slug>-<revision-prefix>` URL is requested
 * and the prefix matches more than one revision under that application. The
 * ingress catches this and returns a 400 with the candidate ids so the caller
 * can re-issue with a longer prefix.
 */
export class AmbiguousRevisionError extends Error {
    constructor(
        readonly applicationId: string,
        readonly prefix: string,
        readonly candidates: string[]
    ) {
        super(`prefix "${prefix}" matches ${candidates.length} revisions on application ${applicationId}`)
        this.name = 'AmbiguousRevisionError'
    }
}

/**
 * Thrown when a preview JWT is required but missing/invalid: a non-live
 * revision invoked without one, or a live-revision mocked run that attached a
 * token which failed verification. Django mints the token on each proxy call
 * (short-lived, bound to the (application, revision) it's invoking). Captured
 * tokens expire in seconds and can't be replayed against a different revision.
 */
export class MissingPreviewSecretError extends Error {
    constructor(readonly reason: string = 'missing_or_invalid_preview_token') {
        super(`non-live revision invoke requires a valid preview token (${reason})`)
        this.name = 'MissingPreviewSecretError'
    }
}

export interface ResolverOpts {
    revisions: RevisionStore
    mode: RoutingMode
    /** For domain mode: the suffix to strip from Host (e.g. ".agents.posthog.com"). */
    domainSuffix?: string
    /** For path mode: the prefix that precedes the slug (e.g. "/agents"). */
    pathPrefix?: string
    /**
     * Shared HMAC signing key for cross-service JWTs (the same value Django
     * + the janitor read from `AGENT_INTERNAL_SIGNING_KEY`). Django mints
     * a short-lived JWT (aud = `agent-ingress.preview`, claims `{ app, rev }`);
     * the caller forwards it as either the `x-agent-preview-token` header
     * (POST/DELETE + the server-side preview-proxy) or the `?preview_token=`
     * query parameter (browser `EventSource` for `/listen`, since
     * EventSource can't set headers). The resolver verifies signature +
     * aud + exp + claim-binding on non-live resolutions. Leave undefined
     * to bypass the gate (dev / harness path).
     */
    internalSigningKey?: string
}

export class RevisionResolver {
    constructor(private readonly opts: ResolverOpts) {}

    async resolveFromHostAndPath(
        host: string | undefined,
        path: string,
        opts?: { providedToken?: string }
    ): Promise<ResolvedAgent | null> {
        let rawSlug: string | null = null
        if (this.opts.mode === 'domain' && host) {
            rawSlug = this.extractSlugFromHost(host)
        } else if (this.opts.mode === 'path') {
            rawSlug = this.extractSlugFromPath(path)
        }
        if (!rawSlug) {
            return null
        }
        return this.resolveBySlug(rawSlug, opts)
    }

    async resolveBySlug(rawSlug: string, opts?: { providedToken?: string }): Promise<ResolvedAgent | null> {
        const resolved = await this.resolveBySlugInner(rawSlug)
        if (!resolved) {
            return null
        }
        // The gate is now the single authority on `isPreview`: it knows
        // whether the revision is live, and whether a valid preview JWT was
        // attached. A non-live revision is always preview (token required); a
        // live revision is preview only when the caller opted in with a token
        // (a mocked run), otherwise it's a real production run.
        const gateResult = await this.assertPreviewGate(resolved, opts?.providedToken)
        return {
            ...resolved,
            isPreview: gateResult.isPreview,
            previewJwtExp: gateResult.exp,
        }
    }

    /**
     * Single resolution path. If `rawSlug` carries a `<slug>-<hex>` suffix,
     * the suffix selects a non-live revision via prefix-match; otherwise we
     * resolve to `application.live_revision`.
     */
    // Inner resolver returns the pair before preview classification — the
    // caller (`resolveBySlug`) stamps `isPreview` after `assertPreviewGate`
    // so we only set the flag once we know the request was authorized.
    private async resolveBySlugInner(
        rawSlug: string
    ): Promise<{ application: AgentApplication; revision: AgentRevision } | null> {
        // Try `<slug>-<8..32 hex>` first. The prefix must be ≥ 8 hex chars to
        // avoid colliding with normal slugs that contain trailing hex (the
        // serializer already forbids trailing `-`, so `slug-` followed by ≥ 8
        // hex chars is unambiguous if `<slug>` resolves to an application).
        const suffixMatch = rawSlug.match(/^(.+)-([0-9a-f]{8,32})$/i)
        if (suffixMatch) {
            const [, baseSlug, prefix] = suffixMatch
            const baseApp = await this.opts.revisions.getApplicationBySlug(baseSlug)
            if (baseApp && !baseApp.archived) {
                const candidates = await this.opts.revisions.listRevisionsByIdPrefix(baseApp.id, prefix)
                const live = candidates.filter((c) => c.state !== 'archived')
                if (live.length === 1) {
                    return { application: baseApp, revision: live[0] }
                }
                if (live.length > 1) {
                    throw new AmbiguousRevisionError(
                        baseApp.id,
                        prefix,
                        live.map((c) => c.id)
                    )
                }
                // No prefix match: fall through to the verbatim slug lookup so
                // a slug that legitimately ends in 8 hex chars still works.
            }
        }

        const application = await this.opts.revisions.getApplicationBySlug(rawSlug)
        if (!application || application.archived || !application.live_revision_id) {
            return null
        }
        // Scope the revision read to the resolved application — the live
        // revision id always belongs to this app, so this is belt-and-braces
        // against ever resolving across a tenant boundary.
        const revision = await this.opts.revisions.getRevisionForApplication(
            application.live_revision_id,
            application.id
        )
        if (!revision) {
            return null
        }
        return { application, revision }
    }

    /**
     * Decide whether this resolution is a preview/MOCKED run, and verify the
     * preview JWT when one is required or supplied. Rules:
     *
     *   - Non-live revision: a valid preview JWT is REQUIRED (running
     *     unpublished code anonymously would be a hole). Always preview.
     *   - Live revision + no token: a real production run. Nothing to verify,
     *     not preview.
     *   - Live revision + token: the caller opted into a mocked run of the
     *     live agent (safe — the live spec is already public; we only suppress
     *     side effects). The token is verified like any other; preview.
     *
     * A presented token must (a) verify against the HMAC, (b) carry the
     * `agent-ingress.preview` audience, (c) not be expired, and (d) carry
     * `app` + `rev` claims matching the resolved revision. The check is
     * bypassed when `internalSigningKey` isn't configured (dev / harness): a
     * non-live revision is preview by definition, and a live revision is
     * treated as a mocked run whenever a token is attached (unverifiable
     * there, but mocking only suppresses side effects, so honoring the intent
     * in dev is safe).
     */
    // Returns the authoritative `isPreview` plus the JWT's `exp` claim (unix
    // seconds) when a preview token was validated, or `exp: null` for a real
    // live run / the dev bypass. Callers attach `exp` to
    // `ResolvedAgent.previewJwtExp` for SSE expiry scheduling.
    private async assertPreviewGate(
        resolved: { application: AgentApplication; revision: AgentRevision },
        providedToken: string | undefined
    ): Promise<{ exp: number | null; isPreview: boolean }> {
        const isLive = resolved.revision.id === resolved.application.live_revision_id

        if (!this.opts.internalSigningKey) {
            // Dev / harness bypass — can't verify, so derive intent: non-live
            // is always preview; live is a mocked run iff a token is attached.
            return { exp: null, isPreview: !isLive || providedToken !== undefined }
        }
        if (isLive && providedToken === undefined) {
            // Real production run against the live revision.
            return { exp: null, isPreview: false }
        }
        // Either non-live (token required) or live-with-token (mocked run
        // opt-in). Both must present a valid preview JWT bound to (app, rev).
        if (!providedToken) {
            throw new MissingPreviewSecretError('missing_token')
        }
        let payload: Record<string, unknown>
        try {
            payload = await verifyInternalJwt({
                token: providedToken,
                audience: INTERNAL_JWT_AUDIENCE.INGRESS_PREVIEW,
                signingKey: this.opts.internalSigningKey,
            })
        } catch (e) {
            throw new MissingPreviewSecretError(`token_verify_failed: ${(e as InternalJwtVerifyError).reason}`)
        }
        if (payload.app !== resolved.application.id) {
            throw new MissingPreviewSecretError('app_claim_mismatch')
        }
        if (payload.rev !== resolved.revision.id) {
            throw new MissingPreviewSecretError('rev_claim_mismatch')
        }
        // `verifyInternalJwt` is jose-backed and rejects expired tokens before
        // returning, so `exp` here is always in the future. A missing `exp`
        // claim would be a verifier contract violation, but if it happens we
        // return null and skip the scheduled expiry event (live-style stream
        // behavior) rather than crash the request.
        const exp = typeof payload.exp === 'number' ? payload.exp : null
        return { exp, isPreview: true }
    }

    /**
     * Returns the canonical "raw slug" form that `resolveBySlugInner` consumes.
     *
     * For a single-label host (`<slug>.agents.posthog.com`) → `<slug>`.
     * For a two-label host (`<hex>.<slug>.agents.posthog.com`) → `<slug>-<hex>`
     * so the suffix matcher inside `resolveBySlugInner` picks up the revision
     * prefix. Production and dev share one resolution code path; only the
     * extractor differs.
     */
    extractSlugFromHost(host: string): string | null {
        const hostNoPort = host.split(':')[0]
        const suffix = this.opts.domainSuffix
        if (!suffix || !hostNoPort.endsWith(suffix)) {
            return null
        }
        const labels = hostNoPort.slice(0, -suffix.length).split('.').filter(Boolean)
        if (labels.length === 1) {
            return labels[0] || null
        }
        if (labels.length === 2 && /^[0-9a-f]{8,32}$/i.test(labels[0])) {
            return `${labels[1]}-${labels[0]}`
        }
        return null
    }

    extractSlugFromPath(path: string): string | null {
        const prefix = this.opts.pathPrefix ?? '/agents'
        if (!path.startsWith(prefix + '/')) {
            return null
        }
        const rest = path.slice(prefix.length + 1)
        const slug = rest.split('/')[0]
        return slug || null
    }
}
