/**
 * Memory tools — S3-backed markdown file store, scoped per
 * (team_id, application_id). Six native tools:
 *
 *   memory-list     — list files under an optional path prefix
 *   memory-search   — substring + tag/path-weighted search over readable files
 *   memory-read     — full body + frontmatter of one file
 *   memory-write    — create a new file (approval-gated by default)
 *   memory-update   — overwrite an existing file (approval-gated by default)
 *   memory-delete   — hard delete one file (approval-gated by default)
 *
 * Writes are always self-scoped. READ tools (list/search/read) accept an
 * optional `owner` (another AgentApplication id): a cross-agent read is honoured
 * only when that owner opted into team-wide sharing (`memory_shared_team_wide`),
 * and `teamId` is never taken from the arg, so cross-team reads are impossible.
 * Otherwise the read returns an `access_denied` envelope.
 */

import {
    defineNativeTool,
    MAX_DESCRIPTION_LEN,
    MemoryConflictError,
    MemoryFile,
    MemoryHeader,
    MemoryNotFoundError,
    MemoryStore,
    searchMemory,
    serializeMemoryDoc,
    Type,
    validateForWrite,
    validateMemoryPath,
    type ToolContext,
} from '@posthog/agent-shared'

// =====================================================================
// Shared envelope shape — all memory tool returns share { ok, error?, data? }
// for consistent surface to the model (matches the PG-era shape, keeps any
// spec referencing this envelope working).
// =====================================================================

const RESULT = Type.Object({
    ok: Type.Boolean(),
    error: Type.Optional(Type.String()),
    data: Type.Optional(Type.Unknown()),
})

type Result<T> = { ok: true; data: T } | { ok: false; error: string }
function ok<T>(data: T): Result<T> {
    return { ok: true, data }
}
function err(error: string): Result<never> {
    return { ok: false, error }
}

// =====================================================================
// Scope + store resolution
// =====================================================================

type Scope = { teamId: number; applicationId: string }
function selfScope(ctx: ToolContext): Scope {
    return { teamId: ctx.teamId, applicationId: ctx.applicationId }
}
// Resolve the read scope. `owner` targets another agent's memory; allowed only
// when that app opted into team-wide sharing. `teamId` is NEVER taken from the
// arg, so cross-team access is impossible by construction. null = access denied.
function readScope(ctx: ToolContext, owner?: string): Scope | null {
    const applicationId = owner ?? ctx.applicationId
    if (applicationId !== ctx.applicationId && !ctx.memoryReadableAppIds?.has(applicationId)) {
        return null
    }
    return { teamId: ctx.teamId, applicationId }
}
const OWNER = Type.Optional(
    Type.String({
        description:
            "Read another agent's memory instead of your own: the owner AgentApplication id. Works only when that agent opted its memory into team-wide sharing (same team); otherwise returns access_denied. Omit to read your own memory.",
    })
)

function storeOrError(ctx: ToolContext): MemoryStore | { error: string } {
    if (!ctx.memoryStore) {
        return { error: 'memory_store_unavailable' }
    }
    return ctx.memoryStore
}

function asError(thrown: unknown): string {
    if (thrown instanceof MemoryNotFoundError) {
        return `not_found: ${thrown.path}`
    }
    if (thrown instanceof MemoryConflictError) {
        return `conflict: ${thrown.message}`
    }
    return (thrown as Error).message ?? 'unknown_error'
}

// =====================================================================
// READ-ONLY TOOLS — no approval gate
// =====================================================================

export const memoryListV1 = defineNativeTool({
    id: '@posthog/memory-list',
    approval: 'allow',
    description:
        'List memory files this agent has stored. Returns one entry per file with its path and short description (no body). Optional `prefix` narrows to a sub-folder, e.g. `incidents/`.',
    args: Type.Object({
        prefix: Type.Optional(
            Type.String({
                description: "Path prefix to scope the list, e.g. 'incidents/' or 'runbooks/oncall/'.",
            })
        ),
        owner: OWNER,
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error)
        }
        const sc = readScope(ctx, args.owner)
        if (!sc) {
            return err(`access_denied: no team-shared memory access to owner '${args.owner}'`)
        }
        try {
            const headers = await s.list(sc, { prefix: args.prefix })
            return ok({
                count: headers.length,
                entries: headers.map((h: MemoryHeader) => ({
                    path: h.path,
                    description: h.frontmatter.description,
                    tags: h.frontmatter.tags,
                    updated_at: h.frontmatter.updatedAt,
                })),
            })
        } catch (e) {
            return err(asError(e))
        }
    },
})

export const memorySearchV1 = defineNativeTool({
    id: '@posthog/memory-search',
    approval: 'allow',
    description:
        "Substring + tag/path weighted search across this agent's memory files. Describe what you're looking for in plain language — the cue is tokenised and scored against descriptions, tags, paths, and bodies. Returns top matches with a one-line snippet.",
    args: Type.Object({
        cue: Type.String({ minLength: 1, description: 'What to look for. Plain natural language is fine.' }),
        prefix: Type.Optional(Type.String({ description: 'Optional path prefix scope.' })),
        limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
        owner: OWNER,
    }),
    returns: RESULT,
    cost_hint: 'medium',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error)
        }
        const sc = readScope(ctx, args.owner)
        if (!sc) {
            return err(`access_denied: no team-shared memory access to owner '${args.owner}'`)
        }
        try {
            const results = await searchMemory(s, sc, args.cue, {
                prefix: args.prefix,
                limit: args.limit,
            })
            return ok({ cue: args.cue, count: results.length, results })
        } catch (e) {
            return err(asError(e))
        }
    },
})

export const memoryReadV1 = defineNativeTool({
    id: '@posthog/memory-read',
    approval: 'allow',
    description:
        'Read one memory file in full — returns its description, tags, timestamps, and full markdown body. Use after `memory-list` or `memory-search` returns a path.',
    args: Type.Object({
        path: Type.String({ description: 'Path returned by list/search, e.g. "incidents/2026/db-pool.md".' }),
        owner: OWNER,
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error)
        }
        const sc = readScope(ctx, args.owner)
        if (!sc) {
            return err(`access_denied: no team-shared memory access to owner '${args.owner}'`)
        }
        try {
            const file: MemoryFile = await s.read(sc, args.path)
            return ok({
                path: file.path,
                description: file.frontmatter.description,
                tags: file.frontmatter.tags,
                created_at: file.frontmatter.createdAt,
                updated_at: file.frontmatter.updatedAt,
                content: file.content,
            })
        } catch (e) {
            return err(asError(e))
        }
    },
})

// =====================================================================
// MUTATING TOOLS — requires_approval=true by default
// (set via the spec.tools entry; the tool def itself doesn't carry the flag)
// =====================================================================

export const memoryWriteV1 = defineNativeTool({
    id: '@posthog/memory-write',
    approval: 'allow',
    description:
        'Create a new memory file. `description` is a one-line summary (<= 280 chars). `content` is the full markdown body. Fails if a file already exists at `path` — use `memory-update` to overwrite. WRITE OPERATIONS ARE APPROVAL-GATED BY DEFAULT — the model will see a synthetic queued result until a human approves.',
    args: Type.Object({
        path: Type.String({
            description:
                'Where to store it. Lowercase a-z 0-9 _ - / only, must end in .md. E.g. "incidents/2026/db-pool.md".',
        }),
        description: Type.String({
            description: `One-line summary, max ${MAX_DESCRIPTION_LEN} chars. Shows up in list/search results.`,
        }),
        content: Type.String({ description: 'Markdown body.' }),
        tags: Type.Optional(
            Type.Array(Type.String(), {
                description: 'Optional flat tags for search ranking. lowercase a-z 0-9 _ - only.',
            })
        ),
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error)
        }
        try {
            validateMemoryPath(args.path)
            validateForWrite({ description: args.description, tags: args.tags })
            const now = new Date().toISOString()
            const raw = serializeMemoryDoc({
                description: args.description,
                tags: args.tags,
                content: args.content,
                createdAt: now,
                updatedAt: now,
            })
            await s.put(selfScope(ctx), args.path, raw, { failIfExists: true })
            ctx.log('info', 'memory.write', { path: args.path })
            return ok({ path: args.path, created_at: now })
        } catch (e) {
            return err(asError(e))
        }
    },
})

export const memoryUpdateV1 = defineNativeTool({
    id: '@posthog/memory-update',
    approval: 'allow',
    description:
        'Overwrite an existing memory file. Any field omitted is taken from the existing file. Fails if the file does not exist. WRITE OPERATIONS ARE APPROVAL-GATED BY DEFAULT.',
    args: Type.Object({
        path: Type.String(),
        description: Type.Optional(Type.String({ description: `One-line summary, max ${MAX_DESCRIPTION_LEN} chars.` })),
        content: Type.Optional(Type.String({ description: 'New markdown body (replaces existing).' })),
        tags: Type.Optional(Type.Array(Type.String())),
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error)
        }
        try {
            validateMemoryPath(args.path)
            const existing = await s.read(selfScope(ctx), args.path)
            const description = args.description ?? existing.frontmatter.description
            const tags = args.tags ?? existing.frontmatter.tags
            const content = args.content ?? existing.content
            validateForWrite({ description, tags })
            const now = new Date().toISOString()
            const raw = serializeMemoryDoc({
                description,
                tags,
                content,
                createdAt: existing.frontmatter.createdAt,
                updatedAt: now,
            })
            await s.put(selfScope(ctx), args.path, raw, { failIfMissing: true })
            ctx.log('info', 'memory.update', { path: args.path })
            return ok({ path: args.path, updated_at: now })
        } catch (e) {
            return err(asError(e))
        }
    },
})

export const memoryDeleteV1 = defineNativeTool({
    id: '@posthog/memory-delete',
    approval: 'allow',
    description: 'Hard-delete a memory file. APPROVAL-GATED BY DEFAULT.',
    args: Type.Object({
        path: Type.String(),
    }),
    returns: RESULT,
    cost_hint: 'cheap',
    async run(args, ctx) {
        const s = storeOrError(ctx)
        if ('error' in s) {
            return err(s.error)
        }
        try {
            validateMemoryPath(args.path)
            await s.delete(selfScope(ctx), args.path)
            ctx.log('info', 'memory.delete', { path: args.path })
            return ok({ path: args.path, deleted: true })
        } catch (e) {
            return err(asError(e))
        }
    },
})
