/**
 * S3-backed memory files HTTP surface. Same code path the runner's
 * `@posthog/memory-*` tools hit — both share `S3MemoryStore` from
 * `@posthog/agent-shared`, so a write here is visible to the agent and vice
 * versa. Django (via `janitor_client.py` + `AgentMemoryViewSet`) proxies the
 * customer-facing UI through these endpoints.
 *
 * Routes are scoped at `/memory/team/:team_id/agent/:application_id/...`.
 * The janitor never resolves slugs; the caller maps slug → application_id
 * before forwarding. Memory paths land in the URL tail via path-to-regexp
 * `(.*)` (e.g. `/files/incidents/2026/db.md` → `incidents/2026/db.md`).
 *
 * Extracted from `server.ts` as the first step of the api/-folder
 * refactor. The other route groups (sessions, approvals, revisions,
 * applications, native-tools) still live in `server.ts` for now — same
 * pattern applies when they get extracted: one file per logical group,
 * each exporting a `mount*Routes(app, opts, log)` function called from
 * `buildJanitorApp`.
 */

import { Express, Request, Response } from 'express'
import { z } from 'zod'

import {
    MAX_DESCRIPTION_LEN,
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryStore,
    Logger,
    parseMemoryDoc,
    searchMemory,
    serializeMemoryDoc,
    validateForWrite,
    validateMemoryPath,
} from '@posthog/agent-shared'

import { asyncHandler } from '../http-utils'

// Per-file ceiling — kept in sync with the bundle ceiling in server.ts. Memory
// files should never approach this, but the cap defends against a malicious
// caller padding the body to exhaust disk / memory.
const MAX_FILE_BYTES = 1_000_000

const MemoryScopeParamsSchema = z.object({
    team_id: z.coerce.number().int().positive('missing_team_id'),
    // application_id is interpolated into the S3 key (the tenancy boundary), so
    // require the UUID shape Django forwards — a non-empty string isn't enough.
    // Matches the tables route's scope schema.
    application_id: z.string().uuid('application_id must be a UUID'),
})

const MemoryListQuerySchema = z.object({
    prefix: z.string().optional(),
})

/**
 * URL-tail capture for the by-path memory routes (read / update / delete).
 * The Express route `/files/:path(.*)` captures everything after `/files/`
 * — including `/` — into `req.params.path`. We re-validate via
 * `validateMemoryPath` inside the handler before any S3 call.
 */
const MemoryPathParamSchema = z.string().min(1, 'missing_path')

const MemorySearchQuerySchema = z.object({
    q: z.string().min(1, 'missing_q'),
    prefix: z.string().optional(),
    limit: z.coerce.number().int().positive().max(100).optional(),
})

const TagsSchema = z.array(z.string().min(1).max(64)).max(32).optional()

const MemoryWriteBodySchema = z.object({
    path: z.string().min(1, 'missing_path'),
    description: z.string().min(1).max(MAX_DESCRIPTION_LEN),
    content: z.string().max(MAX_FILE_BYTES),
    tags: TagsSchema,
})

const MemoryUpdateBodySchema = z.object({
    description: z.string().min(1).max(MAX_DESCRIPTION_LEN).optional(),
    content: z.string().max(MAX_FILE_BYTES).optional(),
    tags: TagsSchema,
})

export interface MountMemoryRoutesOpts {
    /** When omitted, every /memory/* route returns 503. */
    memoryStore?: MemoryStore
    log: Logger
}

export function mountMemoryRoutes(app: Express, opts: MountMemoryRoutesOpts): void {
    function memScope(req: Request): { teamId: number; applicationId: string } {
        const { team_id, application_id } = MemoryScopeParamsSchema.parse(req.params)
        return { teamId: team_id, applicationId: application_id }
    }

    function needMemoryStore(res: Response): MemoryStore | null {
        if (!opts.memoryStore) {
            res.status(503).json({ error: 'memory_store_not_configured' })
            return null
        }
        return opts.memoryStore
    }

    function memoryError(res: Response, err: unknown): void {
        if (err instanceof MemoryNotFoundError) {
            res.status(404).json({ error: 'not_found', path: err.path })
            return
        }
        if (err instanceof MemoryConflictError) {
            res.status(409).json({ error: 'conflict', path: err.path, message: err.message })
            return
        }
        const message = (err as Error).message ?? 'memory_error'
        if (/invalid memory path/i.test(message) || /invalid list prefix/i.test(message)) {
            res.status(400).json({ error: 'invalid_path', message })
            return
        }
        if (/exceeds/.test(message) || /single line/.test(message) || /invalid tag/.test(message)) {
            res.status(400).json({ error: 'invalid_frontmatter', message })
            return
        }
        opts.log.error({ err: message, stack: (err as Error).stack }, 'memory.unhandled')
        res.status(500).json({ error: 'memory_error', message })
    }

    /** GET — list headers under (team, app). Optional ?prefix to scope. */
    app.get(
        '/memory/team/:team_id/agent/:application_id/files',
        asyncHandler(async (req, res) => {
            const store = needMemoryStore(res)
            if (!store) {
                return
            }
            const scope = memScope(req)
            const { prefix } = MemoryListQuerySchema.parse(req.query)
            try {
                const headers = await store.list(scope, { prefix })
                res.json({
                    count: headers.length,
                    entries: headers.map((h) => ({
                        path: h.path,
                        description: h.frontmatter.description,
                        tags: h.frontmatter.tags,
                        created_at: h.frontmatter.createdAt,
                        updated_at: h.frontmatter.updatedAt,
                    })),
                })
            } catch (err) {
                memoryError(res, err)
            }
        })
    )

    /**
     * GET tree — same data as `list` but pre-aggregated as a folder tree
     * so the console doesn't re-derive on every render. Mirror of the
     * shape the bundle tree uses.
     */
    app.get(
        '/memory/team/:team_id/agent/:application_id/tree',
        asyncHandler(async (req, res) => {
            const store = needMemoryStore(res)
            if (!store) {
                return
            }
            const scope = memScope(req)
            try {
                const headers = await store.list(scope)
                interface Node {
                    name: string
                    type: 'folder' | 'file'
                    path?: string
                    description?: string
                    tags?: string[]
                    children?: Node[]
                }
                const root: Node = { name: '', type: 'folder', children: [] }
                for (const h of headers) {
                    const parts = h.path.split('/')
                    let cur = root
                    for (let i = 0; i < parts.length; i++) {
                        const isLeaf = i === parts.length - 1
                        const name = parts[i]
                        cur.children = cur.children ?? []
                        let next = cur.children.find((c) => c.name === name)
                        if (!next) {
                            next = isLeaf
                                ? {
                                      name,
                                      type: 'file',
                                      path: h.path,
                                      description: h.frontmatter.description,
                                      tags: h.frontmatter.tags,
                                  }
                                : { name, type: 'folder', children: [] }
                            cur.children.push(next)
                        }
                        cur = next
                    }
                }
                res.json({ root })
            } catch (err) {
                memoryError(res, err)
            }
        })
    )

    /**
     * GET — read one file in full. The memory path is captured as the URL
     * tail via the path-to-regexp `(.*)` pattern, e.g.
     * `/memory/team/1/agent/<app>/files/incidents/2026/db.md` reads the
     * `incidents/2026/db.md` file. Falls AFTER the bare `/files` (list) route
     * because Express matches in declaration order — that route wins on the
     * tail-less URL.
     */
    app.get(
        '/memory/team/:team_id/agent/:application_id/files/:path(.*)',
        asyncHandler(async (req, res) => {
            const store = needMemoryStore(res)
            if (!store) {
                return
            }
            const scope = memScope(req)
            const path = MemoryPathParamSchema.parse(req.params.path)
            try {
                const file = await store.read(scope, path)
                res.json({
                    path: file.path,
                    description: file.frontmatter.description,
                    tags: file.frontmatter.tags,
                    created_at: file.frontmatter.createdAt,
                    updated_at: file.frontmatter.updatedAt,
                    content: file.content,
                })
            } catch (err) {
                memoryError(res, err)
            }
        })
    )

    /** POST — create a new file (fails if path exists). */
    app.post(
        '/memory/team/:team_id/agent/:application_id/files',
        asyncHandler(async (req, res) => {
            const store = needMemoryStore(res)
            if (!store) {
                return
            }
            const scope = memScope(req)
            const body = MemoryWriteBodySchema.parse(req.body)
            try {
                validateMemoryPath(body.path)
                validateForWrite({ description: body.description, tags: body.tags })
                const now = new Date().toISOString()
                const raw = serializeMemoryDoc({
                    description: body.description,
                    tags: body.tags,
                    content: body.content,
                    createdAt: now,
                    updatedAt: now,
                })
                // Frontmatter pre-flight on the way out the door — catches edge
                // cases where YAML quoting would otherwise corrupt the file.
                const round = parseMemoryDoc(raw)
                if (round.description !== body.description) {
                    res.status(500).json({ error: 'frontmatter_round_trip_failed' })
                    return
                }
                await store.put(scope, body.path, raw, { failIfExists: true })
                res.status(201).json({ path: body.path, created_at: now, updated_at: now })
            } catch (err) {
                memoryError(res, err)
            }
        })
    )

    /** PATCH — update an existing file. Path is the URL tail. Omitted fields are kept. */
    app.patch(
        '/memory/team/:team_id/agent/:application_id/files/:path(.*)',
        asyncHandler(async (req, res) => {
            const store = needMemoryStore(res)
            if (!store) {
                return
            }
            const scope = memScope(req)
            const path = MemoryPathParamSchema.parse(req.params.path)
            const body = MemoryUpdateBodySchema.parse(req.body)
            try {
                validateMemoryPath(path)
                const existing = await store.read(scope, path)
                const description = body.description ?? existing.frontmatter.description
                const tags = body.tags ?? existing.frontmatter.tags
                const content = body.content ?? existing.content
                validateForWrite({ description, tags })
                const now = new Date().toISOString()
                const raw = serializeMemoryDoc({
                    description,
                    tags,
                    content,
                    createdAt: existing.frontmatter.createdAt,
                    updatedAt: now,
                })
                await store.put(scope, path, raw, { failIfMissing: true })
                res.json({
                    path,
                    description,
                    tags,
                    created_at: existing.frontmatter.createdAt,
                    updated_at: now,
                })
            } catch (err) {
                memoryError(res, err)
            }
        })
    )

    /** DELETE — hard delete. Path is the URL tail. */
    app.delete(
        '/memory/team/:team_id/agent/:application_id/files/:path(.*)',
        asyncHandler(async (req, res) => {
            const store = needMemoryStore(res)
            if (!store) {
                return
            }
            const scope = memScope(req)
            const path = MemoryPathParamSchema.parse(req.params.path)
            try {
                await store.delete(scope, path)
                res.json({ path, deleted: true })
            } catch (err) {
                memoryError(res, err)
            }
        })
    )

    /** GET — substring + tag/path-weighted search via MiniSearch (?q=cue). */
    app.get(
        '/memory/team/:team_id/agent/:application_id/search',
        asyncHandler(async (req, res) => {
            const store = needMemoryStore(res)
            if (!store) {
                return
            }
            const scope = memScope(req)
            const { q, prefix, limit } = MemorySearchQuerySchema.parse(req.query)
            try {
                const results = await searchMemory(store, scope, q, { prefix, limit })
                res.json({ cue: q, count: results.length, results })
            } catch (err) {
                memoryError(res, err)
            }
        })
    )
}
