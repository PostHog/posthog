/**
 * Internal HTTP for Django. The janitor doubles as the agent-admin surface
 * because (a) it already runs as a deploy unit, (b) it already has DB +
 * bundle store access, (c) auth is one shared internal secret.
 *
 * Endpoints (grouped):
 *
 *   Session lifecycle (existing):
 *     GET    /sessions?application_id=  list sessions for one application (newest first)
 *     GET    /sessions/:id              full session state
 *     POST   /sessions/:id/cancel       mark failed
 *     POST   /sweep                     trigger a sweep (tests / debug)
 *
 *   Bundle authoring (proxied by the Django API):
 *     GET    /revisions/:id/manifest    list paths + sizes + sha256
 *     GET    /revisions/:id/file        ?path=...  read one file
 *     PUT    /revisions/:id/file        ?path=...  write one file (draft)
 *     DELETE /revisions/:id/file        ?path=...  delete one file (draft)
 *     GET    /revisions/:id/bundle      bulk pull {files: {path: text}}
 *     PUT    /revisions/:id/bundle      bulk push {files, mode: replace|merge}
 *     POST   /revisions/:id/freeze      draft → frozen, returns sha256
 *     POST   /revisions/:id/validate    pre-flight checks (entrypoint, tool ids, custom-tool files, skill paths)
 *     POST   /revisions/:id/clone_from  {source_revision_id, target_revision_id}
 *
 *   Catalog (proxied by Django):
 *     GET    /native_tools              every @posthog/* tool the runner knows
 *
 *   Health:
 *     GET    /healthz
 *
 * Auth: an audience-bound JWT (`x-internal-secret: <jwt>`, aud =
 * `agent-janitor.rpc`) signed with the shared `AGENT_INTERNAL_SIGNING_KEY`.
 * Django keeps the team / scope checks on its side; this layer trusts the
 * request once signature + audience verify.
 *
 * Defensive shape: every async route is wrapped in `asyncHandler` so a
 * rejected promise lands in the global `errorHandler` below instead of
 * becoming an `unhandledRejection`. Bodies + query params are validated
 * with zod at the edge — invalid input returns a structured 400, never a
 * 500 / process crash. See [http-utils.ts](./http-utils.ts).
 */

import express, { Express, NextFunction, Request, Response } from 'express'
import { randomUUID } from 'node:crypto'
import { z } from 'zod'

import {
    acceptedModelIds,
    accumulateUsage,
    AgentRevision,
    AgentRevisionRaw,
    AgentSession,
    AgentSpec,
    AgentSpecSchema,
    ApprovalRequest,
    CatalogModel,
    GatewayCatalog,
    ApprovalStore,
    applyApprovalDecision,
    BundleEntry,
    BundleStore,
    buildSlackManifest,
    buildSystemPrompt,
    createLogger,
    EMPTY_USAGE_TOTAL,
    FRAMEWORK_PROMPT_VERSION,
    handleMetricsRequest,
    instrument,
    INTERNAL_JWT_AUDIENCE,
    InternalJwtVerifyError,
    isDev,
    lastAssistantTextPreview,
    MemoryStore,
    MODEL_POLICY_LEVELS,
    PgIdentityAdminStore,
    previewText,
    readTypedBundle,
    RevisionStore,
    SessionQueue,
    skillBodyPath,
    SPEC_SCHEMA_SECTIONS,
    specJsonSchema,
    TabularStore,
    verifyInternalJwt,
} from '@posthog/agent-shared'
import { getNativeTool, hasNativeTool, listNativeTools } from '@posthog/agent-tools'

import { mountMemoryRoutes } from './api/memory'
import { mountTableRoutes } from './api/tables'
import { buildTypedBundleRouter } from './api/typed-bundle'
import { mountUsersRoutes } from './api/users'
// compile-custom-tools.ts now exports `compileTypedTool` — wired by the
// typed PUT /tools/:id handler, not by freeze. Freeze just validates +
// seals; the compiled.js is already in the bundle by then.
import { fireCronManually } from './cron-tick'
import { asyncHandler, errorHandler, httpMetricsMiddleware, requestLogger } from './http-utils'
import { SweepDeps, sweepOnce } from './sweep'
import { validateRevisionBundle } from './validate-spec'

const log = createLogger('agent-janitor.server')

export interface JanitorServerOpts {
    queue: SessionQueue
    sweep: SweepDeps
    /** Required for the /revisions/* + /native_tools endpoints. */
    revisions?: RevisionStore
    bundles?: BundleStore
    /**
     * Required for the /approvals/* endpoints. When omitted, those routes
     * return 503 so a misconfigured janitor surfaces the gap loudly
     * rather than silently dropping decisions on the floor.
     */
    approvals?: ApprovalStore
    /**
     * S3-backed memory store. Required for the /memory/* endpoints. When
     * omitted those routes return 503 — same convention as `approvals`.
     * Wired from `AGENT_MEMORY_S3_*` in index.ts; tests substitute an
     * `InMemoryMemoryStore` directly.
     */
    memoryStore?: MemoryStore
    /** Read-only tabular store for the console Tables view. */
    tabularStore?: TabularStore
    /**
     * Keyless admin view over agent_user + agent_identity_credential for the
     * console "Users" pane. When omitted, /users/* routes return 503. Holds no
     * decryption key — metadata only.
     */
    identityAdmin?: PgIdentityAdminStore
    /**
     * Shared HMAC signing key — when set, the auth middleware requires
     * `x-internal-secret: <jwt>` with `aud = agent-janitor.rpc` on every
     * non-`/healthz` request. Unset → middleware is skipped (dev / harness).
     */
    internalSigningKey?: string
    /** Served-model catalog. When set, `validate` + freeze reject a models
     *  the gateway doesn't serve; omitted → the model check is skipped. */
    gatewayCatalog?: GatewayCatalog
}

const SessionStateSchema = z.enum(['queued', 'running', 'completed', 'closed', 'failed'])

const ListSessionsQuerySchema = z.object({
    application_id: z.string().min(1, 'missing_application_id'),
    limit: z.coerce.number().int().positive().max(1000).optional(),
    offset: z.coerce.number().int().nonnegative().optional(),
    // `state` can be ?state=completed or ?state=completed,failed
    state: z
        .string()
        .optional()
        .transform((s) => (s ? s.split(',').filter(Boolean) : undefined))
        .pipe(z.array(SessionStateSchema).optional()),
    revision_id: z.string().optional(),
    agent_user_id: z.string().optional(),
    created_after: z.string().optional(),
    created_before: z.string().optional(),
    search: z.string().optional(),
})

const GetSessionQuerySchema = z.object({
    last_n: z.coerce.number().int().nonnegative().optional(),
})

const AggregateForApplicationQuerySchema = z.object({
    application_id: z.string().min(1, 'missing_application_id'),
    /** ISO timestamp — defaults to 24h ago. */
    since: z.string().optional(),
})

const AggregateForTeamQuerySchema = z.object({
    team_id: z.coerce.number().int().positive('missing_team_id'),
    since: z.string().optional(),
})

const ListLiveForTeamQuerySchema = z.object({
    team_id: z.coerce.number().int().positive('missing_team_id'),
    limit: z.coerce.number().int().positive().max(500).optional(),
})

function defaultSince(): string {
    return new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
}

/**
 * Read an approval by id, tenant-scoped to the `?application_id=` query param
 * when Django supplies it (it always does for the per-app approval routes).
 * Scoping here is defence-in-depth — Django also enforces the app/team gate —
 * but it keeps a leaked approval id from resolving another tenant's row at the
 * store layer. Falls back to the unscoped read when no application_id is given.
 */
async function getApprovalScoped(approvals: ApprovalStore, req: Request): Promise<ApprovalRequest | null> {
    const applicationId = typeof req.query.application_id === 'string' ? req.query.application_id : undefined
    return applicationId ? approvals.getForApplication(req.params.id, applicationId) : approvals.get(req.params.id)
}

/**
 * Compute the freeze-time spec: derive `spec.skills[]` + `spec.tools[]` from
 * the typed resources in the bundle and merge them with the author-written
 * non-custom (native/client) tools already on the spec. Pure — the freeze
 * handler persists the result via `revisions.updateSpec`.
 *
 * Authors never write the derived arrays directly — they're computed from
 * the source of truth (the typed-resource state in the bundle) at the
 * freeze instant. This is what makes orphan files structurally impossible:
 * any skill markdown in the bundle gets a spec entry, any tool dir gets a
 * spec entry. Drift requires a writer; there isn't one.
 */
async function deriveSpec(args: {
    revisionId: string
    rev: AgentRevisionRaw
    bundles: BundleStore
    entries?: BundleEntry[]
}): Promise<AgentSpec> {
    const ctx = { revisionId: args.revisionId }
    const { bundle } = await instrument({ key: 'derive.readBundle', log, context: ctx }, () =>
        readTypedBundle(
            args.revisionId,
            args.bundles,
            args.rev.spec as unknown as Record<string, unknown>,
            args.entries
        )
    )
    const derivedSkills = bundle.skills.map((s) => ({
        id: s.id,
        path: skillBodyPath(s.id),
        description: s.description,
    }))
    const derivedTools = bundle.tools.map((t) => ({
        kind: 'custom' as const,
        id: t.id,
        path: `tools/${t.id}`,
    }))

    const authorTools = ((args.rev.spec as Record<string, unknown>).tools as unknown[] | undefined) ?? []
    const preservedTools = authorTools.filter(
        (t) => typeof t === 'object' && t !== null && (t as { kind?: string }).kind !== 'custom'
    )

    const mergedSpec = {
        ...(args.rev.spec as Record<string, unknown>),
        skills: derivedSkills,
        tools: [...preservedTools, ...derivedTools],
        identity_providers: deriveIdentityProviders(args.rev.spec as Record<string, unknown>, preservedTools),
    }
    return instrument({ key: 'derive.parseSpec', log, context: ctx }, () =>
        Promise.resolve(AgentSpecSchema.parse(mergedSpec))
    )
}

/**
 * Auto-wire the managed `posthog` identity provider when a Slack-triggered agent
 * uses native PostHog tools: a Slack asker has no trigger-edge seed, so the link
 * flow needs a provisioned OAuthApplication. We add (or scope-union) the provider
 * with exactly the scopes its tools declare, so promote provisions an app with
 * the right scopes. Chat/MCP agents resolve `posthog` off the seed and don't need
 * this. `binding` defaults are applied by `AgentSpecSchema.parse`.
 */
export function deriveIdentityProviders(spec: Record<string, unknown>, nativeRefs: unknown[]): unknown[] {
    const declared = (spec.identity_providers as Record<string, unknown>[] | undefined) ?? []
    const triggers = (spec.triggers as { type?: string }[] | undefined) ?? []
    if (!triggers.some((t) => t.type === 'slack')) {
        return declared
    }
    const scopes = new Set<string>()
    for (const ref of nativeRefs) {
        const id = (ref as { kind?: string; id?: string }).kind === 'native' ? (ref as { id?: string }).id : undefined
        if (!id || !hasNativeTool(id)) {
            continue
        }
        const provider = getNativeTool(id).schema.requires.provider
        if (provider?.id === 'posthog') {
            for (const s of provider.scopes) {
                scopes.add(s)
            }
        }
    }
    const idx = declared.findIndex((p) => p.kind === 'posthog')
    if (idx === -1 && scopes.size === 0) {
        return declared
    }
    if (idx === -1) {
        return [...declared, { kind: 'posthog', id: 'posthog', scopes: [...scopes].sort() }]
    }
    const existing = declared[idx]
    const merged = [...new Set([...((existing.scopes as string[] | undefined) ?? []), ...scopes])].sort()
    return declared.map((p, i) => (i === idx ? { ...existing, scopes: merged } : p))
}

const BackfillUsageBodySchema = z.object({
    /**
     * Walk sessions for this application. Required so a single call can't
     * scan every session in the cluster — call repeatedly per app.
     */
    application_id: z.string().min(1, 'missing_application_id'),
    /** Count what would change without writing. Default true to keep accidents cheap. */
    dry_run: z.boolean().default(true),
    /** Cap on rows scanned per call so a giant backlog doesn't tie up the request. */
    limit: z.coerce.number().int().positive().max(5000).default(500),
})

const CronFireBodySchema = z.object({
    /** Cron `name` from `spec.triggers[].config.name`. */
    cron_name: z.string().min(1),
    /**
     * Optional client-supplied id so repeated clicks of the same UI "fire
     * now" button dedupe. Without it, every call generates a fresh UUID and
     * fires unconditionally. Stripe-shaped — same convention the
     * Idempotency-Key header uses on the webhook trigger.
     */
    request_id: z.string().min(1).optional(),
    /**
     * Override the firing timestamp. Defaults to "now." Lets the authoring
     * UI replay a historical firing for debugging — placeholder expansion
     * resolves against this timestamp.
     */
    fired_at: z.string().datetime({ offset: true }).optional(),
})

const CloneFromBodySchema = z.object({
    source_revision_id: z.string().min(1, 'missing_source_revision_id'),
})

const ApprovalStateSchema = z.enum(['queued', 'approving', 'dispatched', 'dispatched_failed', 'rejected', 'expired'])

const ListApprovalsQuerySchema = z.object({
    application_id: z.string().min(1, 'missing_application_id'),
    state: z
        .string()
        .optional()
        .transform((s) => (s ? s.split(',').filter(Boolean) : undefined))
        .pipe(z.array(ApprovalStateSchema).optional()),
    limit: z.coerce.number().int().positive().max(500).optional(),
    offset: z.coerce.number().int().nonnegative().optional(),
})

const ListApprovalsForTeamQuerySchema = z.object({
    team_id: z.coerce.number().int().positive('missing_team_id'),
    application_id: z.string().optional(),
    state: z
        .string()
        .optional()
        .transform((s) => (s ? s.split(',').filter(Boolean) : undefined))
        .pipe(z.array(ApprovalStateSchema).optional()),
    limit: z.coerce.number().int().positive().max(500).optional(),
    offset: z.coerce.number().int().nonnegative().optional(),
})

const DecideApprovalBodySchema = z.object({
    decision: z.enum(['approve', 'reject']),
    decided_by: z.string().min(1, 'missing_decided_by'),
    /** Approver-edited args. Only honoured when spec.approval_policy.allow_edit is true. */
    edited_args: z.record(z.string(), z.unknown()).optional(),
    reason: z.string().optional(),
})

interface CatalogModelRow {
    model: string
    provider: string
    context_window: number
    input: number
    output: number
    cache_read?: number
    cache_write?: number
}

/** Per-token USD → per-Mtok, rounded so the UI sees `3` not `0.0000030004`. */
function perMtok(perToken: number | undefined): number | undefined {
    return perToken === undefined ? undefined : Math.round(perToken * 1e6 * 1000) / 1000
}

function catalogToModels(catalog: CatalogModel[]): CatalogModelRow[] {
    return catalog
        .map((m) => {
            const row: CatalogModelRow = {
                model: m.canonical,
                provider: m.owned_by,
                context_window: m.context_window,
                input: perMtok(m.pricing.prompt) ?? 0,
                output: perMtok(m.pricing.completion) ?? 0,
            }
            const cacheRead = perMtok(m.pricing.cache_read)
            const cacheWrite = perMtok(m.pricing.cache_write)
            if (cacheRead !== undefined) {
                row.cache_read = cacheRead
            }
            if (cacheWrite !== undefined) {
                row.cache_write = cacheWrite
            }
            return row
        })
        .sort((a, b) => a.model.localeCompare(b.model))
}

/** Resolve each curated level's members to their catalog canonical id (the
 *  level list uses alias forms); fall back to the raw id when the catalog is
 *  empty or the model isn't served. */
function resolveLevels(catalog: CatalogModel[]): Record<string, string[]> {
    const canonicalFor = (id: string): string => catalog.find((m) => acceptedModelIds([m]).has(id))?.canonical ?? id
    return Object.fromEntries(Object.entries(MODEL_POLICY_LEVELS).map(([level, ids]) => [level, ids.map(canonicalFor)]))
}

export function buildJanitorApp(opts: JanitorServerOpts): Express {
    const app = express()
    // Dev only: serve /metrics on the request port (no dedicated scrape server —
    // three services on one host would collide). First in the chain so scrapes
    // bypass auth + routing. Prod uses the dedicated port.
    if (isDev()) {
        app.use((req, res, next) => {
            if (!handleMetricsRequest(req, res, log)) {
                next()
            }
        })
    }
    // Access log + http metrics before json/auth so they see body-parse 400s,
    // 401s, and 404s too. Every request now leaves one structured `request` line.
    app.use(requestLogger(log))
    app.use(httpMetricsMiddleware())
    // JSON bodies up to 8MB cover any reasonable bundle bulk-push (TS source +
    // a few markdown files). Larger bundles should land an S3 presigned URL
    // path eventually; flagged in the bundle-push action below.
    app.use(express.json({ limit: '8mb' }))
    if (opts.internalSigningKey) {
        const signingKey = opts.internalSigningKey
        app.use((req: Request, res: Response, next: NextFunction) => {
            if (req.path === '/healthz') {
                next()
                return
            }
            const auth = req.headers['x-internal-secret']
            const token = Array.isArray(auth) ? auth[0] : auth
            if (!token) {
                res.status(401).json({ error: 'unauthorized', reason: 'missing_token' })
                return
            }
            verifyInternalJwt({
                token,
                audience: INTERNAL_JWT_AUDIENCE.JANITOR_RPC,
                signingKey,
            })
                .then(() => next())
                .catch((e: InternalJwtVerifyError) => {
                    res.status(401).json({ error: 'unauthorized', reason: e.reason })
                })
        })
    }
    app.get('/healthz', (_req, res) => {
        res.json({ ok: true })
    })

    /* ───────────────────────────── models ─────────────────────────────── */
    // The served-model catalog (id, provider, context, pricing per Mtok) plus
    // the curated auto-level → model map, both from the single source the
    // runner/validation already use. Powers the config-UI model browser (via
    // Django REST) and, through the PostHog MCP, the agent builder's
    // model-choosing skill. Pricing-free on an unreachable gateway (empty list).
    app.get(
        '/models',
        asyncHandler(async (_req, res) => {
            const catalog = opts.gatewayCatalog ? await opts.gatewayCatalog.list() : []
            res.json({ models: catalogToModels(catalog), levels: resolveLevels(catalog) })
        })
    )

    /* ──────────────────────────── spec schema ──────────────────────────── */
    // The agent-spec JSON Schema, emitted from the canonical zod `AgentSpecSchema`
    // (no hand-maintained mirror). Powers the `agent-applications-spec-schema` MCP
    // tool so any client can derive the full spec shape — incl. `spec.models` —
    // from the schema itself instead of guessing. `?section=` returns one
    // top-level slice (e.g. `models`, `triggers`, `limits`) to save tokens.
    app.get(
        '/spec-schema',
        asyncHandler(async (req, res) => {
            const section = typeof req.query.section === 'string' && req.query.section ? req.query.section : undefined
            const result = specJsonSchema(section)
            if (!result) {
                res.status(400).json({
                    error: 'unknown_section',
                    message: `Unknown spec section "${section}". Valid sections: ${SPEC_SCHEMA_SECTIONS.join(', ')}.`,
                    sections: SPEC_SCHEMA_SECTIONS,
                })
                return
            }
            res.json(result)
        })
    )

    /* ───────────────────────────── sessions ───────────────────────────── */

    app.get(
        '/sessions',
        asyncHandler(async (req, res) => {
            const q = ListSessionsQuerySchema.parse(req.query)
            const filter = {
                states: q.state as AgentSession['state'][] | undefined,
                revisionId: q.revision_id,
                agentUserId: q.agent_user_id,
                createdAfter: q.created_after,
                createdBefore: q.created_before,
                search: q.search,
            }
            const [sessions, count] = await Promise.all([
                opts.queue.listSummariesByApplication(q.application_id, {
                    ...filter,
                    limit: q.limit,
                    offset: q.offset,
                }),
                opts.queue.countByApplication(q.application_id, filter),
            ])
            // `turns` + `preview` come off the persisted `turn_count` /
            // `search_text` columns, so listing never detoasts a transcript.
            const summaries = sessions.map((s) => ({
                id: s.id,
                application_id: s.application_id,
                revision_id: s.revision_id,
                state: s.state,
                external_key: s.external_key,
                idempotency_key: s.idempotency_key,
                trigger_metadata: s.trigger_metadata,
                principal: s.principal,
                turns: s.turns,
                preview: previewText(s.search_text),
                usage_total: s.usage_total,
                retry_count: s.retry_count,
                created_at: s.created_at,
                updated_at: s.updated_at,
            }))
            res.json({ results: summaries, count })
        })
    )

    /* ─────────────────────────── fleet stats ─────────────────────────── */
    //
    // Rollups that power the fleet overview tiles. Kept on the
    // janitor (rather than agent-ingress) because (a) Django already
    // proxies through here for read-only authoring data, (b) these are
    // not in the hot per-request path so SELECT-on-jsonb is fine.
    //
    // Registered ahead of `/sessions/:id` — Express matches in order and
    // these literal paths would otherwise be swallowed by the `:id` param.

    app.get(
        '/sessions/stats',
        asyncHandler(async (req, res) => {
            const q = AggregateForApplicationQuerySchema.parse(req.query)
            const [stats, pendingApprovalsCount] = await Promise.all([
                opts.queue.aggregateForApplication(q.application_id, q.since ?? defaultSince()),
                opts.approvals ? opts.approvals.countQueuedByApplication(q.application_id) : Promise.resolve(0),
            ])
            res.json({ ...stats, pendingApprovalsCount })
        })
    )

    app.get(
        '/fleet/stats',
        asyncHandler(async (req, res) => {
            const q = AggregateForTeamQuerySchema.parse(req.query)
            const [stats, pendingApprovalsCount] = await Promise.all([
                opts.queue.aggregateForTeam(q.team_id, q.since ?? defaultSince()),
                opts.approvals ? opts.approvals.countQueuedByTeam(q.team_id) : Promise.resolve(0),
            ])
            res.json({ ...stats, pendingApprovalsCount })
        })
    )

    app.get(
        '/sessions/live',
        asyncHandler(async (req, res) => {
            const q = ListLiveForTeamQuerySchema.parse(req.query)
            const sessions = await opts.queue.listLiveForTeam(q.team_id, { limit: q.limit })
            const summaries = sessions.map((s) => ({
                id: s.id,
                application_id: s.application_id,
                revision_id: s.revision_id,
                team_id: s.team_id,
                state: s.state,
                external_key: s.external_key,
                principal: s.principal,
                turns: s.conversation.length,
                preview: lastAssistantTextPreview(s.conversation),
                usage_total: s.usage_total,
                created_at: s.created_at,
                updated_at: s.updated_at,
            }))
            res.json({ results: summaries })
        })
    )

    app.get(
        '/sessions/:id',
        asyncHandler(async (req, res) => {
            const q = GetSessionQuerySchema.parse(req.query)
            const s = await opts.queue.get(req.params.id)
            if (!s) {
                res.status(404).json({ error: 'not_found' })
                return
            }
            // Optional ?last_n=<int> returns just the tail of the conversation —
            // useful for huge sessions where the caller only cares about the most
            // recent turns. usage_total comes off the row regardless so cost
            // reporting stays accurate.
            if (q.last_n !== undefined && q.last_n < s.conversation.length) {
                res.json({
                    ...s,
                    conversation: s.conversation.slice(-q.last_n),
                    conversation_total_turns: s.conversation.length,
                    conversation_trimmed: true,
                })
                return
            }
            res.json({ ...s, conversation_trimmed: false })
        })
    )
    app.post(
        '/sessions/:id/cancel',
        asyncHandler(async (req, res) => {
            const s = await opts.queue.get(req.params.id)
            if (!s) {
                res.status(404).json({ error: 'not_found' })
                return
            }
            // Cancel is idempotent on terminal states — mirrors the chat
            // `/cancel` semantics.
            if (s.state === 'closed' || s.state === 'failed' || s.state === 'cancelled') {
                res.json({ ok: true, idempotent: true, state: s.state })
                return
            }
            await opts.queue.update(req.params.id, { state: 'cancelled' })
            res.json({ ok: true, state: 'cancelled' })
        })
    )
    app.post(
        '/sweep',
        asyncHandler(async (_req, res) => {
            const result = await sweepOnce(opts.sweep)
            res.json(result)
        })
    )

    // Recompute `usage_total` from `conversation` for sessions created before
    // the column existed (or where a backwards-compat write zeroed it).
    app.post(
        '/sessions/backfill_usage',
        asyncHandler(async (req, res) => {
            const body = BackfillUsageBodySchema.parse(req.body)
            const sessions = await opts.queue.listByApplication(body.application_id, { limit: body.limit })
            let scanned = 0
            let updated = 0
            for (const s of sessions) {
                scanned++
                const recomputed = s.conversation.reduce((acc, msg) => {
                    if (msg.role !== 'assistant' || !msg.usage) {
                        return acc
                    }
                    return accumulateUsage(acc, msg)
                }, EMPTY_USAGE_TOTAL)
                if (usageMatches(s.usage_total, recomputed)) {
                    continue
                }
                updated++
                if (!body.dry_run) {
                    await opts.queue.update(s.id, { usage_total: recomputed })
                }
            }
            res.json({ scanned, updated, dry_run: body.dry_run })
        })
    )

    /* ───────────────────────────── approvals ───────────────────────────── */
    //
    // Approval-gated tools.
    //
    // Django proxies through here for the list / show / decide surface so
    // the runtime DB (`agent_tool_approval_request`) stays node-owned, the
    // same way bundle CRUD goes via /revisions/*. The decide endpoint also
    // owns the wake path: mark the row, write the wake marker into
    // pending_inputs, flip session state back to `queued` so the runner
    // picks it up. For reject / no-edit-approve the synthetic tool_result
    // is materialised here too; for approve the runner dispatches the
    // tool on its next turn (so sandbox / secrets / integrations stay in
    // their existing home — see plan §B in the design doc).

    const needApprovalStore = (res: Response): boolean => {
        if (!opts.approvals) {
            res.status(503).json({ error: 'approval_store_not_configured' })
            return false
        }
        return true
    }

    const summariseApproval = (r: ApprovalRequest): Record<string, unknown> => ({
        id: r.id,
        session_id: r.session_id,
        application_id: r.application_id,
        team_id: r.team_id,
        revision_id: r.revision_id,
        turn: r.turn,
        tool_call_id: r.tool_call_id,
        tool_name: r.tool_name,
        proposed_args: r.proposed_args,
        decided_args: r.decided_args,
        assistant_message: r.assistant_message,
        approver_scope: r.approver_scope,
        state: r.state,
        decision_by: r.decision_by,
        decision_at: r.decision_at,
        decision_reason: r.decision_reason,
        dispatch_outcome: r.dispatch_outcome,
        created_at: r.created_at,
        expires_at: r.expires_at,
    })

    app.get(
        '/approvals',
        asyncHandler(async (req, res) => {
            if (!needApprovalStore(res)) {
                return
            }
            const q = ListApprovalsQuerySchema.parse(req.query)
            const rows = await opts.approvals!.listByApplication(q.application_id, {
                state: q.state,
                limit: q.limit,
                offset: q.offset,
            })
            res.json({ results: rows.map(summariseApproval) })
        })
    )

    // Fleet-wide list — Django's `/agent_fleet/approvals/` proxies through here.
    // Filters by team, optionally narrows to a single application. Same row
    // shape as `/approvals` so the console can render either response with one
    // component. When both team_id and application_id are present we still go
    // through listByTeam so we cross-check ownership in a single round-trip.
    app.get(
        '/fleet/approvals',
        asyncHandler(async (req, res) => {
            if (!needApprovalStore(res)) {
                return
            }
            const q = ListApprovalsForTeamQuerySchema.parse(req.query)
            const rows = await opts.approvals!.listByTeam(q.team_id, {
                state: q.state,
                applicationId: q.application_id,
                limit: q.limit,
                offset: q.offset,
            })
            res.json({ results: rows.map(summariseApproval) })
        })
    )

    app.get(
        '/approvals/:id',
        asyncHandler(async (req, res) => {
            if (!needApprovalStore(res)) {
                return
            }
            const row = await getApprovalScoped(opts.approvals!, req)
            if (!row) {
                res.status(404).json({ error: 'not_found' })
                return
            }
            res.json(summariseApproval(row))
        })
    )

    app.post(
        '/approvals/:id/decide',
        asyncHandler(async (req, res) => {
            if (!needApprovalStore(res)) {
                return
            }
            const body = DecideApprovalBodySchema.parse(req.body)
            // Defence-in-depth tenant scope; Django always supplies it on the
            // per-app routes. The shared helper runs the decide + wake so the
            // ingress principal-decision API drives the identical transition.
            const applicationId = typeof req.query.application_id === 'string' ? req.query.application_id : undefined
            const result = await applyApprovalDecision(
                { approvals: opts.approvals!, queue: opts.queue },
                {
                    requestId: req.params.id,
                    applicationId,
                    decision: body.decision,
                    decidedBy: body.decided_by,
                    reason: body.reason,
                    editedArgs: body.edited_args,
                }
            )
            if (!result.ok) {
                const status = result.error === 'not_found' ? 404 : result.error === 'edits_not_allowed' ? 422 : 409
                res.status(status).json(
                    result.state ? { error: result.error, state: result.state } : { error: result.error }
                )
                return
            }
            res.json({ ok: true, state: result.state })
        })
    )

    /* ───────────────────────────── catalog ───────────────────────────── */

    // Catalog of every @posthog/* native tool the runner knows about. The MCP
    // shows this to authoring models so they can pick tools to put in
    // spec.tools without guessing ids. Cached at module load — no DB call.
    app.get('/native_tools', (_req, res) => {
        res.json({ tools: listNativeTools() })
    })

    /* ───────────────────────────── revisions ───────────────────────────── */

    const needRevisionStore = (res: Response): boolean => {
        if (!opts.revisions || !opts.bundles) {
            res.status(503).json({ error: 'revision_store_not_configured' })
            return false
        }
        return true
    }

    const requireDraft = async (
        res: Response,
        revisionId: string
    ): Promise<{ rev: Awaited<ReturnType<RevisionStore['getRevisionRaw']>> } | null> => {
        // Raw read: clone_from + freeze only care about state + bundle pointers
        // here, not the parsed spec. A drifted source spec would otherwise
        // block re-seeding from inside the very flow that overwrites it.
        const rev = await opts.revisions!.getRevisionRaw(revisionId)
        if (!rev) {
            res.status(404).json({ error: 'revision_not_found' })
            return null
        }
        if (rev.state !== 'draft') {
            res.status(409).json({ error: 'revision_not_editable', state: rev.state })
            return null
        }
        // Bundle-store `.frozen` marker is authoritative — Django stamps
        // `state='ready'` after the janitor returns, but the marker is
        // written first and is consistent across processes. Catches the
        // narrow window between janitor.freeze and Django's state write,
        // and any operator who poked the marker directly.
        if (opts.bundles && (await opts.bundles.isFrozen(revisionId))) {
            res.status(409).json({ error: 'revision_not_editable', state: 'ready' })
            return null
        }
        return { rev }
    }

    app.get(
        '/revisions/:id/manifest',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const entries = await opts.bundles!.list(req.params.id)
            res.json({
                revision_id: req.params.id,
                state: rev.state,
                bundle_sha256: rev.bundle_sha256,
                files: entries,
            })
        })
    )

    // Deterministic Slack app manifest for the revision's slack trigger. The
    // public request URLs are computed Django-side (only Django knows
    // AGENT_INGRESS_PUBLIC_URL + the slug) and passed in as query params; the
    // janitor supplies the spec, the app display info, and the native-tool
    // scope catalog. 400 when the revision has no slack trigger.
    app.get(
        '/revisions/:id/slack-manifest',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const application = await opts.revisions!.getApplication(rev.application_id)
            if (!application) {
                res.status(404).json({ error: 'application_not_found' })
                return
            }
            const eventsUrl = typeof req.query.events_url === 'string' ? req.query.events_url : null
            const interactivityUrl =
                typeof req.query.interactivity_url === 'string' ? req.query.interactivity_url : null
            // Slack scopes only: a tool contributes to the Slack app manifest
            // iff its single credential provider is the `slack` bot. PostHog /
            // other identity-provider scopes never leak into the Slack manifest.
            const scopeByTool = new Map(
                listNativeTools().map((t) => [
                    t.id,
                    t.schema.requires.provider?.id === 'slack' ? t.schema.requires.provider.scopes : [],
                ])
            )
            try {
                const { manifest, notes } = buildSlackManifest({
                    triggers: rev.spec.triggers ?? [],
                    tools: rev.spec.tools ?? [],
                    displayName: application.name,
                    displayDescription: application.description,
                    eventsUrl,
                    interactivityUrl,
                    scopesForNativeTool: (id) => scopeByTool.get(id) ?? [],
                })
                res.json({ revision_id: req.params.id, manifest, notes })
            } catch (err) {
                if (err instanceof Error && err.message === 'no_slack_trigger') {
                    res.status(400).json({ error: 'no_slack_trigger' })
                    return
                }
                throw err
            }
        })
    )

    // Typed bundle authoring API. The legacy file-grain endpoints
    // (`/file?path=X`, `/bundle` with `mode`) were removed. The new
    // surface lives entirely under the typed router below.
    if (opts.revisions && opts.bundles) {
        app.use('/revisions/:id', buildTypedBundleRouter({ revisions: opts.revisions, bundles: opts.bundles }))
    }

    app.post(
        '/revisions/:id/freeze',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            // Already-frozen revisions: re-derive the sha + spec from the
            // existing manifest and return them. Lets callers recover from
            // the case where the janitor wrote `.frozen` but the HTTP
            // response was lost in flight.
            if (opts.bundles && opts.revisions && (await opts.bundles.isFrozen(req.params.id))) {
                const idCtx = { revisionId: req.params.id }
                const entries = await instrument({ key: 'freeze.idempotent.list', log, context: idCtx }, () =>
                    opts.bundles!.list(req.params.id)
                )
                const rev = await opts.revisions.getRevision(req.params.id)
                let derivedSpec: AgentSpec | null = null
                if (rev) {
                    derivedSpec = await instrument({ key: 'freeze.idempotent.derive', log, context: idCtx }, () =>
                        deriveSpec({ revisionId: req.params.id, rev, bundles: opts.bundles!, entries })
                    )
                }
                const { createHash } = await import('node:crypto')
                const hash = createHash('sha256')
                for (const e of entries) {
                    hash.update(e.path).update('\0').update(e.sha256).update('\0')
                }
                res.json({
                    ok: true,
                    state: 'ready',
                    bundle_sha256: hash.digest('hex'),
                    idempotent: true,
                    derived_spec: derivedSpec,
                })
                return
            }
            const ok = await requireDraft(res, req.params.id)
            if (!ok) {
                return
            }
            const ctx = { revisionId: req.params.id }
            const entries = await instrument({ key: 'freeze.list', log, context: ctx }, () =>
                opts.bundles!.list(req.params.id)
            )
            const derivedSpec = await instrument(
                { key: 'freeze.derive', log, context: { ...ctx, files: entries.length } },
                () =>
                    deriveSpec({
                        revisionId: req.params.id,
                        rev: ok.rev!,
                        bundles: opts.bundles!,
                        entries,
                    })
            )
            const validateInput: AgentRevision = { ...ok.rev!, spec: derivedSpec }
            const freezeCatalog = opts.gatewayCatalog ? await opts.gatewayCatalog.list() : []
            const report = await instrument({ key: 'freeze.validate', log, context: ctx }, () =>
                validateRevisionBundle(validateInput, opts.bundles!, freezeCatalog)
            )
            if (!report.ok) {
                res.status(422).json({ error: 'validation_failed', report })
                return
            }
            const sha = await instrument({ key: 'freeze.seal', log, context: { ...ctx, files: entries.length } }, () =>
                opts.bundles!.freeze(req.params.id, entries)
            )
            // Persist the derived spec now that the bundle is sealed + validated.
            // Safe to write from the janitor: Django's freeze proxy no longer
            // wraps this call in `transaction.atomic()`, so it holds no
            // `agent_revision` row lock for our UPDATE to deadlock against. The
            // revision is still `draft` here (Django flips it to `ready` after we
            // return), so updateSpec's draft guard passes. Django re-stamps the
            // same spec alongside state + sha — harmless belt-and-suspenders.
            await instrument({ key: 'freeze.persistSpec', log, context: ctx }, () =>
                opts.revisions!.updateSpec(req.params.id, derivedSpec)
            )
            res.json({ ok: true, state: 'ready', bundle_sha256: sha, derived_spec: derivedSpec })
        })
    )

    app.post(
        '/revisions/:id/validate',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const validateCatalog = opts.gatewayCatalog ? await opts.gatewayCatalog.list() : []
            const report = await validateRevisionBundle(rev, opts.bundles!, validateCatalog)
            res.json(report)
        })
    )

    // Manually fire one cron job — same execution path the scheduler walks,
    // but on demand. Authoring path: the user clicks "fire now" in the
    // console (or the concierge MCP tool
    // `agent-applications-revisions-cron-fire-create`) and gets back the
    // session id without having to wait for the next real firing. Without
    // this, "did my cron prompt do the right thing?" is unanswerable until
    // the cron actually fires. Plan §9 "Manual fire".
    //
    // Dedupe shape `cron-manual:<rev>:<name>:<request_id>` — distinct from
    // the scheduled `cron:<rev>:<name>:<minute>` form, so manual + scheduled
    // firings at the same minute don't collide. The caller can supply
    // `request_id` to make repeated clicks idempotent (the UI does this);
    // omitting it generates a fresh UUID, which makes every call a new fire.
    app.post(
        '/revisions/:id/cron/fire',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const app_ = await opts.revisions!.getApplication(rev.application_id)
            if (!app_) {
                res.status(404).json({ error: 'application_not_found' })
                return
            }
            const body = CronFireBodySchema.parse(req.body)
            const trigger = rev.spec.triggers.find((t) => t.type === 'cron' && t.config.name === body.cron_name)
            if (!trigger || trigger.type !== 'cron') {
                res.status(404).json({ error: 'unknown_cron', cron_name: body.cron_name })
                return
            }
            const requestId = body.request_id ?? randomUUID()
            const result = await fireCronManually(
                { revisions: opts.revisions!, queue: opts.queue },
                {
                    rev,
                    app: app_,
                    cronName: body.cron_name,
                    requestId,
                    firedAt: body.fired_at ? new Date(body.fired_at) : undefined,
                }
            )
            res.json({ ok: true, ...result, request_id: requestId })
        })
    )

    // Render the fully-assembled system prompt for a revision —
    // framework preamble + agent.md + skills index. Authors (via the
    // Django proxy / MCP) use this to inspect what the model will
    // actually see before promotion. Plan §4 (framework-system-prompt.md).
    app.get(
        '/revisions/:id/system-prompt',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const systemPrompt = await buildSystemPrompt(rev, opts.bundles!)
            res.json({
                revision_id: req.params.id,
                framework_prompt_version: FRAMEWORK_PROMPT_VERSION,
                system_prompt: systemPrompt,
            })
        })
    )

    app.post(
        '/revisions/:id/clone_from',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const { source_revision_id: sourceId } = CloneFromBodySchema.parse(req.body)
            const ok = await requireDraft(res, req.params.id)
            if (!ok) {
                return
            }
            // Parallel copy — sequential was the cause of new_draft_create
            // timing out at the 30s Django proxy on bundles with 15+ files,
            // leaving a half-cloned draft. S3 server-side copy doesn't move
            // bytes through this process so the only ceiling is the S3
            // client connection pool, which handles dozens fine.
            const cloneCtx = { revisionId: req.params.id, sourceRevisionId: sourceId }
            const src = await instrument({ key: 'clone_from.list', log, context: cloneCtx }, () =>
                opts.bundles!.list(sourceId)
            )
            await instrument({ key: 'clone_from.copy', log, context: { ...cloneCtx, files: src.length } }, () =>
                Promise.all(src.map((entry) => opts.bundles!.copy(sourceId, entry.path, req.params.id, entry.path)))
            )
            const files = await opts.bundles!.list(req.params.id)
            res.json({ ok: true, source_revision_id: sourceId, files })
        })
    )

    /* ──────────────────────── extracted route groups ───────────────────── */
    //
    // First step of the api/-folder refactor — memory routes live in
    // src/api/memory.ts. The remaining groups (sessions, approvals,
    // revisions, applications, native-tools) still inline above; same
    // pattern applies when they get extracted: one file per logical group,
    // each exporting `mount*Routes(app, opts, log)` called here.
    mountMemoryRoutes(app, { memoryStore: opts.memoryStore, log })
    mountTableRoutes(app, { tabularStore: opts.tabularStore, log })
    mountUsersRoutes(app, { identityAdmin: opts.identityAdmin, log })

    // Last in the chain. Catches anything the route handlers threw (via
    // asyncHandler), translates ZodError → 400, everything else → 500.
    app.use(errorHandler(log))

    return app
}

function usageMatches(a: typeof EMPTY_USAGE_TOTAL, b: typeof EMPTY_USAGE_TOTAL): boolean {
    return (
        a.tokens_in === b.tokens_in &&
        a.tokens_out === b.tokens_out &&
        a.cache_read === b.cache_read &&
        a.cache_write === b.cache_write &&
        a.cost_input === b.cost_input &&
        a.cost_output === b.cost_output &&
        a.cost_cache_read === b.cost_cache_read &&
        a.cost_cache_write === b.cost_cache_write &&
        a.cost_total === b.cost_total
    )
}
