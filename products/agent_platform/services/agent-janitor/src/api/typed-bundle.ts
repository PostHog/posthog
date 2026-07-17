/**
 * Typed bundle authoring HTTP surface — `GET /bundle`, `PUT /bundle`,
 * `PUT /agent_md`, `PUT /spec`, single-resource skill + tool PUTs and
 * DELETEs.
 *
 * Replaces the legacy file-grain endpoints (`PUT /file?path=X`,
 * `PUT /bundle` with `mode`, etc.). The author never writes a path; the
 * server translates typed payloads into the canonical S3 layout.
 *
 * Resources:
 *   - `agent_md`            ← the system prompt (string)
 *   - `skills/<id>`         ← { description, body, files? }  (SKILL.md + companions under skills/<id>/)
 *   - `tools/<id>`          ← { description, args_schema, source }
 *   - `spec`                ← author-facing slice (no skills[]/tools[])
 *
 * Tool PUTs run the AST shape check + esbuild compile synchronously and
 * return 422 with structured diagnostics on failure (mirrored from
 * `compileTypedTool`). The bundle is left untouched on failure.
 *
 * The runner still reads the same S3 layout it always did; the freeze
 * step (separate handler) derives `spec.skills[]` / `spec.tools[]` and
 * stamps them into the frozen revision's spec.
 */

import { Router } from 'express'
import { randomUUID } from 'node:crypto'
import { z } from 'zod'

import {
    AgentSpecSchema,
    BundleStore,
    deleteSkillFiles,
    deleteToolFiles,
    readTypedBundle,
    RESOURCE_ID_REGEX,
    RevisionState,
    RevisionStore,
    SandboxPool,
    skillBodyPath,
    skillCompanionPath,
    syncBundleToStore,
    toolCapabilitiesPath,
    toolCompiledPath,
    toolSchemaPath,
    TypedBundleSchema,
    TypedSkillSchema,
    TypedSpecSchema,
    TypedToolSchema,
    writeToolSourceAndSchema,
} from '@posthog/agent-shared'

import { compileTypedTool } from '../compile-custom-tools'
import { asyncHandler } from '../http-utils'

const ResourceIdParamSchema = z
    .string()
    .min(1)
    .max(64)
    .regex(RESOURCE_ID_REGEX, { message: 'id must be lowercase letters, digits, hyphens, or underscores' })

// A skill companion file (e.g. `references/api.md`, `scripts/setup.sh`) shipped
// alongside SKILL.md. `path` is relative to the skill folder; it's resolved +
// safety-checked against `skillCompanionPath` in the handler. Limits mirror the
// llma-skill store (≤50 files, ≤1 MB each) so a store skill round-trips cleanly.
const SkillFilePutSchema = z.object({
    path: z.string().min(1).max(255),
    content: z.string().max(1_000_000),
})
const SkillPutBodySchema = TypedSkillSchema.omit({ id: true }).extend({
    // Store skills allow a ≤1 MB body and render_skill_md prepends frontmatter,
    // so allow headroom above the store cap. (Limits mirror the llma-skill store
    // so a resolved store skill round-trips cleanly into the bundle.)
    body: z.string().max(1_100_000),
    files: z.array(SkillFilePutSchema).max(50).default([]),
})
const ToolPutBodySchema = TypedToolSchema.omit({ id: true })

const AgentMdPutBodySchema = z.object({
    content: z.string().max(500_000),
})

const SpecPutBodySchema = z.object({
    spec: TypedSpecSchema,
})

const TypedBundlePutBodySchema = TypedBundleSchema.omit({ skills: true })

export interface TypedBundleRouterOpts {
    revisions: RevisionStore
    bundles: BundleStore
    /**
     * Single-shot sandbox pool for `POST /tools/:tool_id/dry_run`. Same
     * `selectSandboxPool` impl the runner uses; lifecycle is per-call
     * (acquire → invoke → release) rather than per-session. Omitted →
     * the dry-run route 503s.
     */
    sandboxes?: SandboxPool
    /** Wall-clock cap per dry-run invocation (ms). Default: 10 000. */
    dryRunWallMs?: number
    /** Memory cap per dry-run sandbox (MB). Default: 256. */
    dryRunMemoryMb?: number
    /** Max dry-run sandboxes in flight at once (janitor-wide). Default: 2. */
    dryRunMaxConcurrent?: number
}

const DEFAULT_DRY_RUN_WALL_MS = 10_000
const DEFAULT_DRY_RUN_MEMORY_MB = 256
const DEFAULT_DRY_RUN_MAX_CONCURRENT = 2
// Extra headroom past the in-sandbox `timeoutMs` before the janitor-side
// wall clock trips, so the dispatcher's cooperative timeout gets first
// chance to report the friendlier per-tool error.
const DRY_RUN_TIMEOUT_GRACE_MS = 1_000

const WALL_CLOCK_EXCEEDED = Symbol('wall_clock_exceeded')

/**
 * Race a promise against a hard wall clock. The in-sandbox dispatcher
 * enforces `timeoutMs` cooperatively (a Promise.race inside the sandbox
 * process), so a tool whose body is a synchronous busy-loop blocks the
 * sandbox event loop and the invoke never returns — without this outer
 * race the handler would hang, its `finally` would never run, and the
 * in-flight slot would stay pinned until the janitor restarts.
 */
function raceWallClock<T>(promise: Promise<T>, ms: number): Promise<T | typeof WALL_CLOCK_EXCEEDED> {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => resolve(WALL_CLOCK_EXCEEDED), ms)
        promise.then(
            (value) => {
                clearTimeout(timer)
                resolve(value)
            },
            (err: unknown) => {
                clearTimeout(timer)
                reject(err)
            }
        )
    })
}

const DryRunBodySchema = z.object({
    /** Synthetic args the tool's `actions.default` is called with. */
    args: z.unknown(),
    /**
     * Optional `{secret_name → opaque_nonce}` map plumbed into the
     * sandbox the same way the runner injects nonces during a real
     * session. The plaintext value never enters the sandbox, so the
     * stub only needs *some* string the tool's `ctx.secrets.ref(name)`
     * can return. Authors typically pass placeholder strings here just
     * to confirm the tool runs without throwing `secret not provisioned`.
     */
    mock_secrets: z.record(z.string(), z.string()).optional(),
})

/**
 * Build the router that owns the typed-bundle endpoints. Mounted by the main
 * server under `/revisions/:id`.
 */
export function buildTypedBundleRouter(opts: TypedBundleRouterOpts): Router {
    const router = Router({ mergeParams: true })

    // ─── GET /bundle ────────────────────────────────────────────────
    router.get(
        '/bundle',
        asyncHandler(async (req, res) => {
            const rev = await opts.revisions.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const { bundle, warnings } = await readTypedBundle(
                rev.id,
                opts.bundles,
                rev.spec as Record<string, unknown>
            )
            res.json({
                revision_id: rev.id,
                state: rev.state,
                bundle_sha256: rev.bundle_sha256,
                bundle,
                warnings,
            })
        })
    )

    // ─── PUT /bundle  (full replace) ────────────────────────────────
    router.put(
        '/bundle',
        asyncHandler(async (req, res) => {
            if (!(await assertDraft(opts, req.params.id, res))) {
                return
            }
            const parsed = TypedBundlePutBodySchema.safeParse(req.body)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_request', issues: parsed.error.issues })
                return
            }
            const payload = parsed.data

            // Pre-compile every tool BEFORE touching S3 — fail-fast so a
            // bad tool doesn't half-replace the bundle.
            const compileResults = await compileAllTools(payload.tools)
            const failed = compileResults.filter((r) => !r.result.ok)
            if (failed.length > 0) {
                res.status(422).json({
                    error: 'tool_compile_failed',
                    tools: failed.map((f) => ({ tool_id: f.tool_id, errors: f.result.errors })),
                })
                return
            }

            await syncBundleToStore(req.params.id, opts.bundles, payload)
            for (const { tool, result } of compileResults) {
                await writeToolSourceAndSchema(req.params.id, opts.bundles, tool)
                await opts.bundles.write(req.params.id, toolCompiledPath(tool.id), result.compiled_js!)
                if (result.capabilities) {
                    await opts.bundles.write(
                        req.params.id,
                        toolCapabilitiesPath(tool.id),
                        JSON.stringify(result.capabilities, null, 2)
                    )
                }
            }

            // Persist the author-facing spec onto agent_revision.spec.
            // skills/tools stay empty at this layer — derived at freeze.
            await persistAuthorSpec(opts, req.params.id, payload.spec)

            res.json({ ok: true })
        })
    )

    // ─── PUT /agent_md ──────────────────────────────────────────────
    router.put(
        '/agent_md',
        asyncHandler(async (req, res) => {
            if (!(await assertDraft(opts, req.params.id, res))) {
                return
            }
            const parsed = AgentMdPutBodySchema.safeParse(req.body)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_request', issues: parsed.error.issues })
                return
            }
            await opts.bundles.write(req.params.id, 'agent.md', parsed.data.content)
            res.json({ ok: true, bytes: Buffer.byteLength(parsed.data.content, 'utf8') })
        })
    )

    // ─── PUT /spec ──────────────────────────────────────────────────
    router.put(
        '/spec',
        asyncHandler(async (req, res) => {
            if (!(await assertDraft(opts, req.params.id, res))) {
                return
            }
            const parsed = SpecPutBodySchema.safeParse(req.body)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_request', issues: parsed.error.issues })
                return
            }
            await persistAuthorSpec(opts, req.params.id, parsed.data.spec)
            res.json({ ok: true })
        })
    )

    // ─── PUT /skills/:skill_id (upsert) ─────────────────────────────
    router.put(
        '/skills/:skill_id',
        asyncHandler(async (req, res) => {
            const idCheck = ResourceIdParamSchema.safeParse(req.params.skill_id)
            if (!idCheck.success) {
                res.status(400).json({ error: 'invalid_resource_id', issues: idCheck.error.issues })
                return
            }
            if (!(await assertDraft(opts, req.params.id, res))) {
                return
            }

            const parsed = SkillPutBodySchema.safeParse(req.body)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_request', issues: parsed.error.issues })
                return
            }
            const id = idCheck.data
            // Resolve + safety-check every companion path BEFORE touching the
            // store, so invalid input can't half-clear an existing skill folder.
            let companions: { path: string; content: string }[]
            try {
                companions = parsed.data.files.map((f) => ({
                    path: skillCompanionPath(id, f.path),
                    content: f.content,
                }))
            } catch (e) {
                res.status(400).json({ error: 'invalid_skill_file_path', message: (e as Error).message })
                return
            }
            // Clear the skill folder first so a re-PUT sweeps SKILL.md plus any
            // stale companions before writing the fresh body + companion set.
            await deleteSkillFiles(req.params.id, opts.bundles, id)
            await opts.bundles.write(req.params.id, skillBodyPath(id), parsed.data.body)
            for (const c of companions) {
                await opts.bundles.write(req.params.id, c.path, c.content)
            }
            res.json({ ok: true, skill_id: id, files_written: companions.length })
        })
    )

    // ─── DELETE /skills/:skill_id ───────────────────────────────────
    router.delete(
        '/skills/:skill_id',
        asyncHandler(async (req, res) => {
            const idCheck = ResourceIdParamSchema.safeParse(req.params.skill_id)
            if (!idCheck.success) {
                res.status(400).json({ error: 'invalid_resource_id', issues: idCheck.error.issues })
                return
            }
            if (!(await assertDraft(opts, req.params.id, res))) {
                return
            }
            const exists = await opts.bundles.exists(req.params.id, skillBodyPath(idCheck.data))
            if (!exists) {
                res.status(404).json({ error: 'skill_not_found', skill_id: idCheck.data })
                return
            }
            await deleteSkillFiles(req.params.id, opts.bundles, idCheck.data)
            res.json({ ok: true, skill_id: idCheck.data })
        })
    )

    // ─── PUT /tools/:tool_id (upsert with AST + compile) ────────────
    router.put(
        '/tools/:tool_id',
        asyncHandler(async (req, res) => {
            const idCheck = ResourceIdParamSchema.safeParse(req.params.tool_id)
            if (!idCheck.success) {
                res.status(400).json({ error: 'invalid_resource_id', issues: idCheck.error.issues })
                return
            }
            if (!(await assertDraft(opts, req.params.id, res))) {
                return
            }

            const parsed = ToolPutBodySchema.safeParse(req.body)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_request', issues: parsed.error.issues })
                return
            }
            const id = idCheck.data
            const tool = { id, ...parsed.data }

            const compile = await compileTypedTool({ tool_id: id, source: tool.source })
            if (!compile.ok) {
                res.status(422).json({ error: 'tool_compile_failed', tool_id: id, errors: compile.errors })
                return
            }

            await writeToolSourceAndSchema(req.params.id, opts.bundles, tool)
            await opts.bundles.write(req.params.id, toolCompiledPath(id), compile.compiled_js!)
            if (compile.capabilities) {
                await opts.bundles.write(
                    req.params.id,
                    toolCapabilitiesPath(id),
                    JSON.stringify(compile.capabilities, null, 2)
                )
            }
            res.json({ ok: true, tool_id: id, capabilities: compile.capabilities })
        })
    )

    // ─── DELETE /tools/:tool_id ─────────────────────────────────────
    router.delete(
        '/tools/:tool_id',
        asyncHandler(async (req, res) => {
            const idCheck = ResourceIdParamSchema.safeParse(req.params.tool_id)
            if (!idCheck.success) {
                res.status(400).json({ error: 'invalid_resource_id', issues: idCheck.error.issues })
                return
            }
            if (!(await assertDraft(opts, req.params.id, res))) {
                return
            }
            const sourcePath = `tools/${idCheck.data}/source.ts`
            const exists = await opts.bundles.exists(req.params.id, sourcePath)
            if (!exists) {
                res.status(404).json({ error: 'tool_not_found', tool_id: idCheck.data })
                return
            }
            await deleteToolFiles(req.params.id, opts.bundles, idCheck.data)
            res.json({ ok: true, tool_id: idCheck.data })
        })
    )

    // ─── POST /tools/:tool_id/dry_run  (single-shot sandbox execution) ──
    //
    // Runs the persisted compiled.js once with caller-supplied args + a
    // stubbed ctx (mock nonces only — no real secrets ever leave Django).
    // Per-call lifecycle (acquire → invoke → release) so we don't carry
    // session-shaped sandbox state. May split out into `agent-exec` later
    // if execution duties grow enough to crowd out CRUD.
    //
    // In-flight cap: dry-run spawns sandboxes outside the session
    // execution queue, so without a bound a caller with agents:write
    // could exhaust the sandbox backend by hammering this route. A
    // process-wide counter is the right scope — this is an availability
    // guard for the janitor host / shared backend, not per-team fairness
    // (revisit if dry-run traffic ever justifies a per-team quota).
    let dryRunsInFlight = 0
    router.post(
        '/tools/:tool_id/dry_run',
        asyncHandler(async (req, res) => {
            const idCheck = ResourceIdParamSchema.safeParse(req.params.tool_id)
            if (!idCheck.success) {
                res.status(400).json({ error: 'invalid_resource_id', issues: idCheck.error.issues })
                return
            }
            if (!opts.sandboxes) {
                res.status(503).json({ error: 'sandbox_pool_not_configured' })
                return
            }
            if (!(await assertDraft(opts, req.params.id, res))) {
                return
            }
            const parsed = DryRunBodySchema.safeParse(req.body)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_request', issues: parsed.error.issues })
                return
            }
            const toolId = idCheck.data

            // Confirm the tool exists in the bundle. We could load and pass
            // through the sandbox, but the explicit check produces a 404
            // instead of a cryptic `tool_not_found` runtime error.
            const compiledPath = toolCompiledPath(toolId)
            const compiledJs = await opts.bundles.readText(req.params.id, compiledPath).catch(() => null)
            if (compiledJs === null) {
                res.status(404).json({ error: 'tool_not_found', tool_id: toolId })
                return
            }
            const schemaText = await opts.bundles.readText(req.params.id, toolSchemaPath(toolId)).catch(() => '{}')
            let schemaJson: unknown = {}
            try {
                schemaJson = JSON.parse(schemaText)
            } catch {
                // Schema is informational at the sandbox boundary; carry on.
                schemaJson = {}
            }

            // We need a teamId for the AcquireOpts contract; the dry-run is
            // tied to the revision's owning team. Revisions don't carry
            // team_id directly — resolve it through the parent application.
            const rev = await opts.revisions.getRevisionRaw(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const app = await opts.revisions.getApplication(rev.application_id)
            if (!app) {
                res.status(404).json({ error: 'application_not_found' })
                return
            }

            const wallMs = opts.dryRunWallMs ?? DEFAULT_DRY_RUN_WALL_MS
            const memoryMb = opts.dryRunMemoryMb ?? DEFAULT_DRY_RUN_MEMORY_MB
            const sessionId = `dry-run-${randomUUID()}`
            const startedAt = Date.now()

            // Build the response in stages so `duration_ms` is captured
            // consistently — after `release()` runs in the finally — on
            // every path (acquire failure, invoke throw, invoke not-ok,
            // invoke ok). Each failure mode gets its own stable `code`
            // so authors can tell infrastructure problems
            // (`sandbox_acquire_failed`) from tool-side problems
            // (`sandbox_invoke_failed`, or the dispatcher's own code on
            // an `ok:false` invoke result like `secret_not_provisioned`
            // / `timeout`).
            let status = 200
            let body: {
                ok: boolean
                result?: unknown
                error?: { code: string; message: string }
            } = { ok: false, error: { code: 'dry_run_unknown', message: 'no response produced' } }
            let sandbox: Awaited<ReturnType<SandboxPool['acquireForSession']>> | undefined

            // Admission control before any sandbox is acquired. 429 (not a
            // queue) — dry-run is interactive; the author just retries.
            const maxConcurrent = opts.dryRunMaxConcurrent ?? DEFAULT_DRY_RUN_MAX_CONCURRENT
            if (dryRunsInFlight >= maxConcurrent) {
                res.status(429).json({ error: 'dry_run_throttled', max_concurrent: maxConcurrent })
                return
            }
            dryRunsInFlight++
            try {
                try {
                    sandbox = await opts.sandboxes.acquireForSession({
                        sessionId,
                        teamId: app.team_id,
                        tools: [
                            {
                                id: toolId,
                                compiledJs,
                                schemaJson,
                            },
                        ],
                        nonces: parsed.data.mock_secrets ?? {},
                        sessionTimeoutMs: wallMs,
                        limits: { wallMs, memoryMb },
                    })
                } catch (err) {
                    status = 500
                    body = {
                        ok: false,
                        error: { code: 'sandbox_acquire_failed', message: (err as Error).message },
                    }
                }
                if (sandbox) {
                    try {
                        const invokeResult = await raceWallClock(
                            sandbox.invoke({
                                toolId,
                                action: 'default',
                                args: parsed.data.args,
                                timeoutMs: wallMs,
                            }),
                            wallMs + DRY_RUN_TIMEOUT_GRACE_MS
                        )
                        if (invokeResult === WALL_CLOCK_EXCEEDED) {
                            // Same stable code the dispatcher reports for a
                            // cooperative timeout, so authors see one shape.
                            // The finally's release destroys the wedged
                            // sandbox, which also unblocks the abandoned
                            // invoke promise.
                            body = {
                                ok: false,
                                error: {
                                    code: 'timeout',
                                    message: `tool did not return within ${wallMs}ms (janitor-side wall clock)`,
                                },
                            }
                        } else {
                            body = invokeResult.ok
                                ? { ok: true, result: invokeResult.result }
                                : { ok: false, error: invokeResult.error }
                        }
                    } catch (err) {
                        status = 500
                        body = {
                            ok: false,
                            error: { code: 'sandbox_invoke_failed', message: (err as Error).message },
                        }
                    }
                }
            } finally {
                if (sandbox) {
                    await opts.sandboxes.release(sessionId).catch(() => {
                        // Sandbox release is best-effort cleanup; the sweep
                        // reaper catches anything we miss. Don't let a slow
                        // release surface as a request failure.
                    })
                }
                dryRunsInFlight--
                const durationMs = Date.now() - startedAt
                res.status(status).json({ tool_id: toolId, ...body, duration_ms: durationMs })
            }
        })
    )

    return router
}

// ─── helpers ────────────────────────────────────────────────────────

async function assertDraft(
    opts: TypedBundleRouterOpts,
    revisionId: string,
    res: import('express').Response
): Promise<boolean> {
    // Raw read: the state + frozen-marker checks below don't need a parsed
    // spec, and a re-seed that overwrites a drifted source spec must not
    // be blocked by the drift it's about to fix.
    const rev = await opts.revisions.getRevisionRaw(revisionId)
    if (!rev) {
        res.status(404).json({ error: 'revision_not_found' })
        return false
    }
    if (rev.state !== ('draft' satisfies RevisionState)) {
        res.status(409).json({ error: 'revision_not_draft', state: rev.state })
        return false
    }
    // The bundle store's `.frozen` marker is the authoritative cross-
    // process signal — Django stamps `state='ready'` after the janitor
    // returns from freeze, so there's a brief window where state=draft
    // but the bundle is already frozen on disk. Mirror the legacy
    // `requireDraft` check (server.ts) here.
    if (await opts.bundles.isFrozen(revisionId)) {
        res.status(409).json({ error: 'revision_not_draft', state: 'ready' })
        return false
    }
    return true
}

async function compileAllTools<T extends { id: string; source: string }>(
    tools: T[]
): Promise<{ tool_id: string; tool: T; result: Awaited<ReturnType<typeof compileTypedTool>> }[]> {
    const out: { tool_id: string; tool: T; result: Awaited<ReturnType<typeof compileTypedTool>> }[] = []
    for (const t of tools) {
        const r = await compileTypedTool({ tool_id: t.id, source: t.source })
        out.push({ tool_id: t.id, tool: t, result: r })
    }
    return out
}

/**
 * Persist the author-facing spec onto `agent_revision.spec`. The runtime
 * spec includes empty `skills[]` and `tools[]` arrays — those become
 * populated at freeze from the typed resources in the bundle. The runner
 * never sees a non-frozen revision, so it doesn't matter that drafts have
 * empty arrays.
 */
async function persistAuthorSpec(
    opts: TypedBundleRouterOpts,
    revisionId: string,
    authorSpec: z.infer<typeof TypedSpecSchema>
): Promise<void> {
    // Raw read: we treat the existing spec as a JSONB blob for the merge —
    // every author field gets overlaid by `authorSpec` and the final result
    // is parsed strictly below, so a drifted source spec is fine here.
    const rev = await opts.revisions.getRevisionRaw(revisionId)
    if (!rev) {
        throw new Error('revision_not_found')
    }
    const existing = (rev.spec ?? {}) as Record<string, unknown>
    const merged: Record<string, unknown> = {
        ...existing,
        ...authorSpec,
        // Author cannot write these — they're server-derived at freeze.
        // Leave existing values alone if Django seeded them; otherwise default to [].
        skills: existing.skills ?? [],
        tools: existing.tools ?? [],
    }
    // Parse loosely — defaults fill anything the partial author payload
    // doesn't supply (model, triggers, mcps, etc.).
    const parsed = AgentSpecSchema.parse(merged)
    await opts.revisions.updateSpec(revisionId, parsed)
}
