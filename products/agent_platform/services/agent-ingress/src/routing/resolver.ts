/**
 * Map an inbound request to an AgentApplication + a revision.
 *
 * Live invokes never carry revision info; the resolver looks up the
 * application's `live_revision_id`.
 *
 * Non-live invokes carry the revision-id-hex as part of the URL:
 *
 *   - "domain" (prod): `<rev-hex-prefix>.<slug>.agents.posthog.com`
 *     For example `019e6f25.weekly-digest.agents.posthog.com`.
 *   - "path"   (dev) : `/agents/<slug>-<rev-hex-prefix>/...`
 *     For example `/agents/weekly-digest-019e6f25/run`.
 *
 * The prefix can be 8–32 hex chars (no dashes). 32 = the full UUID with
 * dashes stripped; 8 is the ergonomic short form for human-shared URLs.
 */

import { AgentApplication, AgentRevision, RevisionStore } from '@posthog/agent-shared'

export type RoutingMode = 'domain' | 'path'

export interface ResolvedAgent {
    application: AgentApplication
    revision: AgentRevision
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

export interface ResolverOpts {
    revisions: RevisionStore
    mode: RoutingMode
    /** For domain mode: the suffix to strip from Host (e.g. ".agents.posthog.com"). */
    domainSuffix?: string
    /** For path mode: the prefix that precedes the slug (e.g. "/agents"). */
    pathPrefix?: string
}

export class RevisionResolver {
    constructor(private readonly opts: ResolverOpts) {}

    async resolveFromHostAndPath(host: string | undefined, path: string): Promise<ResolvedAgent | null> {
        let rawSlug: string | null = null
        if (this.opts.mode === 'domain' && host) {
            rawSlug = this.extractSlugFromHost(host)
        } else if (this.opts.mode === 'path') {
            rawSlug = this.extractSlugFromPath(path)
        }
        if (!rawSlug) {
            return null
        }
        return this.resolveBySlug(rawSlug)
    }

    async resolveBySlug(rawSlug: string): Promise<ResolvedAgent | null> {
        return this.resolveBySlugInner(rawSlug)
    }

    /**
     * Single resolution path. If `rawSlug` carries a `<slug>-<hex>` suffix,
     * the suffix selects a non-live revision via prefix-match; otherwise we
     * resolve to `application.live_revision`.
     */
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
