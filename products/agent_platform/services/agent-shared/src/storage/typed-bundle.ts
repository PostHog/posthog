/**
 * Typed bundle — the structured authoring view on top of the S3 bundle.
 *
 * The S3 layout below the surface is unchanged:
 *   - `agent.md`                        ← author's system prompt
 *   - `skills/<id>/SKILL.md`            ← skill markdown body (one folder per skill,
 *                                         compatible with the `SKILL.md` convention
 *                                         used by external agent-skill frameworks)
 *   - `tools/<id>/source.ts`            ← TypeScript source (author writes)
 *   - `tools/<id>/compiled.js`          ← esbuild output (server writes)
 *   - `tools/<id>/schema.json`          ← derived from PUT body (server writes)
 *
 * The author-facing API never references file paths. They write to typed
 * resources (`PUT /skills/:id`, `PUT /tools/:id`) and the janitor translates
 * to canonical S3 paths under the hood.
 *
 * `readTypedBundle` and `writeTypedBundle` are the round-trip helpers used
 * by `GET /bundle` and `PUT /bundle` respectively. Single-resource endpoints
 * (`PUT /skills/:id`, etc.) reach into the bundle store directly with the
 * canonical paths defined below.
 */

import { z } from 'zod'

import { SecretRefSchema } from '../spec/spec'
import { BundleEntry, BundleStore } from './bundle'

// ─── Canonical S3 paths ──────────────────────────────────────────────

export const AGENT_MD_PATH = 'agent.md'
export const SKILL_BODY_FILENAME = 'SKILL.md'
export function skillBodyPath(skillId: string): string {
    return `skills/${skillId}/${SKILL_BODY_FILENAME}`
}

/**
 * Resolve a skill companion file's relative path to its canonical bundle path
 * (`skills/<id>/<rel>`), rejecting anything that would escape the skill folder
 * or collide with the reserved `SKILL.md` body. Mirrors the runtime guard in
 * `@posthog/load-skill`'s `resolveSkillFile` so what we write is exactly what
 * the loader will later accept. Throws on invalid input.
 */
export function skillCompanionPath(skillId: string, relPath: string): string {
    const rel = relPath.replace(/\\/g, '/')
    if (!rel || rel.startsWith('/')) {
        throw new Error(`skill file "${relPath}" must be a non-empty relative path inside the skill folder.`)
    }
    const segments = rel.split('/')
    if (segments.some((s) => s === '..' || s === '.' || s === '')) {
        throw new Error(`skill file "${relPath}" must not contain traversal or empty segments.`)
    }
    if (rel === SKILL_BODY_FILENAME) {
        throw new Error(`skill file "${relPath}" is reserved — the body is written from the skill's \`body\`.`)
    }
    return `skills/${skillId}/${rel}`
}
export function toolSourcePath(toolId: string): string {
    return `tools/${toolId}/source.ts`
}
export function toolCompiledPath(toolId: string): string {
    return `tools/${toolId}/compiled.js`
}
export function toolSchemaPath(toolId: string): string {
    return `tools/${toolId}/schema.json`
}
export function toolCapabilitiesPath(toolId: string): string {
    return `tools/${toolId}/capabilities.json`
}

// ─── Typed resource shapes ──────────────────────────────────────────

// Slugs are url-safe ids the author picks. Tight regex keeps S3 paths sane
// and matches the convention the existing skill / tool ids already follow.
export const RESOURCE_ID_REGEX = /^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$/
const ResourceIdSchema = z
    .string()
    .min(1)
    .max(64)
    .regex(RESOURCE_ID_REGEX, { message: 'id must be lowercase letters, digits, hyphens, or underscores' })

export const TypedSkillSchema = z.object({
    id: ResourceIdSchema,
    description: z.string().min(1).max(2000),
    body: z.string().max(200_000),
})

/**
 * Capability metadata the AST walker derives at compile time. Stored on
 * the bundle as `tools/<id>/capabilities.json` so the authoring UI can
 * surface it without re-parsing the source on every read. Optional on the
 * typed shape so old bundles (compiled before capabilities existed) round-
 * trip without warnings — the read path treats a missing file as "no
 * capabilities known."
 */
export const TypedToolCapabilitiesSchema = z.object({
    secret_refs: z.array(z.string()).default([]),
    dynamic_secret_refs: z.boolean().default(false),
})

export type TypedToolCapabilities = z.infer<typeof TypedToolCapabilitiesSchema>

export const TypedToolSchema = z.object({
    id: ResourceIdSchema,
    description: z.string().min(1).max(2000),
    /**
     * JSON Schema for the tool's args. Free-form object (the runner doesn't
     * introspect it; pi-ai passes it through to the provider). Enforced as
     * a non-null object so the model sees a parseable schema.
     */
    args_schema: z.record(z.string(), z.unknown()),
    source: z.string().min(1).max(500_000),
    /**
     * Server-stamped at compile time; authors don't set it on the way in.
     * Optional so existing bundles (and write paths that don't have the
     * compile result handy yet) round-trip cleanly.
     */
    capabilities: TypedToolCapabilitiesSchema.optional(),
})

export type TypedSkill = z.infer<typeof TypedSkillSchema>
export type TypedTool = z.infer<typeof TypedToolSchema>

/**
 * Author-facing spec slice — everything the author writes via PUT /spec.
 * Excludes `skills[]` / `tools[]` because those are server-derived at
 * freeze from the typed resources in the bundle.
 *
 * Validation is shallow on purpose: the janitor's PUT /spec endpoint just
 * stashes this onto `agent_revision.spec`. The full `AgentSpecSchema` is
 * applied at freeze when the derived skills/tools are merged in.
 */
export const TypedSpecSchema = z
    .object({
        models: z.unknown().optional(),
        triggers: z.array(z.unknown()).optional(),
        mcps: z.array(z.unknown()).optional(),
        identity_providers: z.array(z.unknown()).optional(),
        // The canonical secret shape: a bare key string OR a host-scoped
        // `{ name, allowed_hosts }` object. Reuse `SecretRefSchema` (the single
        // source of truth) rather than re-spelling it — the old string-only
        // array silently rejected host-scoped secrets at bundle PUT.
        secrets: z.array(SecretRefSchema).optional(),
        limits: z.unknown().optional(),
        reasoning: z.string().optional(),
        framework_prompt: z.unknown().optional(),
        resume: z.unknown().optional(),
    })
    .strict()

export type TypedSpec = z.infer<typeof TypedSpecSchema>

export const TypedBundleSchema = z.object({
    agent_md: z.string(),
    skills: z.array(TypedSkillSchema),
    tools: z.array(TypedToolSchema),
    spec: TypedSpecSchema,
})

export type TypedBundle = z.infer<typeof TypedBundleSchema>

// ─── Read: S3 → TypedBundle ─────────────────────────────────────────

/**
 * Reconstruct the typed view from the S3 bundle contents + the revision
 * spec. Skips files that don't fit the canonical schema (best-effort; lets
 * malformed legacy bundles still produce a partial typed view rather than
 * 500ing the GET).
 *
 * Tools must have BOTH source.ts and schema.json to be included; bundles
 * with only one half are reported as broken via `errors`.
 */
export interface ReadTypedBundleResult {
    bundle: TypedBundle
    /** Non-fatal complaints — bundle files that don't fit the canonical layout. */
    warnings: string[]
}

export async function readTypedBundle(
    revisionId: string,
    store: BundleStore,
    spec: Record<string, unknown> = {},
    precomputedEntries?: BundleEntry[]
): Promise<ReadTypedBundleResult> {
    const warnings: string[] = []
    const entries = precomputedEntries ?? (await store.list(revisionId))
    const paths = new Set(entries.map((e) => e.path))

    // Read every interesting file in parallel — S3 is the bottleneck, and
    // sequential reads of a ~14-skill bundle were timing out the Django proxy
    // (30s) during the typed-API rollout. Parallel reads bring a freeze of
    // a 50-file bundle down from ~25s to ~2s.
    const reads = await Promise.all([
        paths.has(AGENT_MD_PATH) ? store.readText(revisionId, AGENT_MD_PATH) : Promise.resolve(''),
        ...entries.map(async (entry) => ({ path: entry.path, content: await store.readText(revisionId, entry.path) })),
    ])
    const agentMd = reads[0] as string
    const fileContents = new Map<string, string>()
    for (let i = 1; i < reads.length; i++) {
        const r = reads[i] as { path: string; content: string }
        fileContents.set(r.path, r.content)
    }

    // Skills: every `skills/<id>/SKILL.md` whose `<id>` matches the slug regex.
    const skillsByid = new Map<string, { description: string; body: string }>()
    for (const entry of entries) {
        const m = /^skills\/([a-z0-9](?:[a-z0-9_-]*[a-z0-9])?)\/SKILL\.md$/.exec(entry.path)
        if (!m) {
            continue
        }
        const id = m[1]
        const body = fileContents.get(entry.path) ?? ''
        const description = deriveSkillDescription(body)
        skillsByid.set(id, { description, body })
    }

    const skills: TypedSkill[] = []
    for (const [id, slot] of skillsByid) {
        skills.push({ id, description: slot.description, body: slot.body })
    }
    skills.sort((a, b) => a.id.localeCompare(b.id))

    // Tools: every `tools/<id>/` directory that has source.ts + schema.json.
    const toolDirs = new Set<string>()
    for (const entry of entries) {
        const m = /^tools\/([a-z0-9](?:[a-z0-9_-]*[a-z0-9])?)\//.exec(entry.path)
        if (m) {
            toolDirs.add(m[1])
        }
    }
    const tools: TypedTool[] = []
    for (const id of [...toolDirs].sort()) {
        const sourcePresent = paths.has(toolSourcePath(id))
        const schemaPresent = paths.has(toolSchemaPath(id))
        if (!sourcePresent) {
            warnings.push(`tool dir tools/${id}/ missing source.ts`)
            continue
        }
        if (!schemaPresent) {
            warnings.push(`tool dir tools/${id}/ missing schema.json`)
            continue
        }
        const source = fileContents.get(toolSourcePath(id)) ?? ''
        const schemaText = fileContents.get(toolSchemaPath(id)) ?? '{}'
        let schema: Record<string, unknown> = {}
        let description = ''
        try {
            const parsed = JSON.parse(schemaText) as Record<string, unknown>
            if (parsed && typeof parsed === 'object') {
                description = typeof parsed.description === 'string' ? parsed.description : ''
                const argsSchema = parsed.args_schema
                if (argsSchema && typeof argsSchema === 'object' && !Array.isArray(argsSchema)) {
                    schema = argsSchema as Record<string, unknown>
                }
            }
        } catch {
            warnings.push(`tool ${id} schema.json is not valid JSON`)
        }

        // Optional capabilities.json — present for tools compiled after the
        // capability extractor landed. Missing/malformed = no capability
        // metadata exposed (rather than failing the bundle read).
        let capabilities: TypedToolCapabilities | undefined
        const capabilitiesPath = toolCapabilitiesPath(id)
        if (paths.has(capabilitiesPath)) {
            const capsText = fileContents.get(capabilitiesPath) ?? '{}'
            try {
                const parsed = TypedToolCapabilitiesSchema.safeParse(JSON.parse(capsText))
                if (parsed.success) {
                    capabilities = parsed.data
                } else {
                    warnings.push(`tool ${id} capabilities.json failed schema validation`)
                }
            } catch {
                warnings.push(`tool ${id} capabilities.json is not valid JSON`)
            }
        }

        tools.push({ id, description, args_schema: schema, source, capabilities })
    }

    return {
        bundle: {
            agent_md: agentMd,
            skills,
            tools,
            spec: stripDerivedSpecFields(spec),
        },
        warnings,
    }
}

/**
 * Derive a skill's one-line description from its `SKILL.md`. Prefers the YAML
 * frontmatter `description:` — the authored signal the model uses to decide
 * when to load a skill — and falls back to the first prose line of the body
 * when there's no frontmatter or no `description:` field. Capped at 280 chars.
 *
 * The frontmatter parse matters: without it, a `SKILL.md` that opens with the
 * conventional `---` fence yields `"---"` as the description (the fence is the
 * first non-heading line), which silently kills the model's load signal.
 */
export function deriveSkillDescription(raw: string): string {
    const fm = splitFrontmatter(raw)
    if (fm) {
        const desc = frontmatterDescription(fm.block)
        if (desc) {
            return desc.slice(0, 280)
        }
    }
    // No frontmatter description — first non-empty, non-heading prose line of
    // the body (skipping the frontmatter block when present).
    for (const line of (fm ? fm.body : raw).split('\n')) {
        const t = line.trim()
        if (!t || t.startsWith('#')) {
            continue
        }
        return t.slice(0, 280)
    }
    return ''
}

/** Split a leading `---`-fenced YAML frontmatter block off a SKILL.md.
 *  Returns the block + the body after it, or null when the file doesn't open
 *  with a terminated frontmatter fence. */
function splitFrontmatter(raw: string): { block: string; body: string } | null {
    const lines = raw.split('\n')
    if (lines[0]?.trim() !== '---') {
        return null
    }
    for (let i = 1; i < lines.length; i++) {
        if (lines[i].trim() === '---') {
            return { block: lines.slice(1, i).join('\n'), body: lines.slice(i + 1).join('\n') }
        }
    }
    return null // unterminated fence — treat as no frontmatter
}

/** The `description:` value from a frontmatter block, surrounding quotes
 *  stripped. Empty string when absent. Plain scalars only — these SKILL.md
 *  files don't use folded/block YAML for the description. */
function frontmatterDescription(block: string): string {
    for (const line of block.split('\n')) {
        const m = /^description:\s*(.*)$/.exec(line)
        if (m) {
            return m[1].trim().replace(/^["']|["']$/g, '')
        }
    }
    return ''
}

/**
 * Strip the runtime-derived fields from a spec before exposing it on the
 * authoring API. `skills[]` and `tools[]` are owned by the typed resources
 * in the bundle; the API caller mutates the resources, not the spec arrays.
 */
export function stripDerivedSpecFields(spec: Record<string, unknown>): TypedSpec {
    const { skills: _s, tools: _t, ...rest } = spec ?? {}
    // Best-effort coerce — the spec column is JSONB so the runtime guarantees
    // an object shape. We trust the persistence layer.
    return rest as TypedSpec
}

// ─── Write: TypedBundle → S3 ─────────────────────────────────────────

/**
 * Sync the bundle store to match the typed view. Used by `PUT /bundle`.
 * - Files matching the typed layout for resources NOT in the payload are
 *   deleted (full replace).
 * - The author-facing spec (`bundle.spec`) is returned for the caller to
 *   stamp onto `agent_revision.spec` — this helper doesn't touch Postgres.
 *
 * The caller is responsible for:
 *   - tool compilation (calling `compileAndWriteTool` per tool)
 *   - persisting `bundle.spec` onto the revision row
 */
export async function syncBundleToStore(
    revisionId: string,
    store: BundleStore,
    bundle: Omit<TypedBundle, 'skills'>
): Promise<void> {
    const entries = await store.list(revisionId)
    const existing = new Set(entries.map((e) => e.path))

    // Build the set of paths we WILL write so we know what to delete. Skills are
    // NOT managed here — they're materialized from the store at freeze and live
    // only in the frozen bundle, so the full-replace never touches `skills/`.
    const willWrite = new Set<string>()
    willWrite.add(AGENT_MD_PATH)
    for (const tool of bundle.tools) {
        willWrite.add(toolSourcePath(tool.id))
        willWrite.add(toolSchemaPath(tool.id))
        willWrite.add(toolCompiledPath(tool.id))
        willWrite.add(toolCapabilitiesPath(tool.id))
    }

    // Delete anything in the canonical layout that's NOT in the new payload.
    // We DON'T touch paths outside the canonical layout (future-resource buckets
    // or legacy junk) and we DON'T touch `skills/` (freeze-owned).
    for (const path of existing) {
        if (willWrite.has(path)) {
            continue
        }
        if (path === AGENT_MD_PATH || path.startsWith('tools/')) {
            await store.delete(revisionId, path)
        }
    }

    // Write agent.md. Tools are written by the caller after the compile step.
    await store.write(revisionId, AGENT_MD_PATH, bundle.agent_md)
}

/**
 * Write one tool's source.ts + schema.json. compiled.js is written
 * separately by the upload pipeline after the AST + esbuild steps succeed.
 */
export async function writeToolSourceAndSchema(revisionId: string, store: BundleStore, tool: TypedTool): Promise<void> {
    await store.write(revisionId, toolSourcePath(tool.id), tool.source)
    await store.write(
        revisionId,
        toolSchemaPath(tool.id),
        JSON.stringify({ description: tool.description, args_schema: tool.args_schema }, null, 2)
    )
}

/**
 * Delete one tool's bundle files (source.ts, compiled.js, schema.json).
 */
export async function deleteToolFiles(revisionId: string, store: BundleStore, toolId: string): Promise<void> {
    for (const path of [
        toolSourcePath(toolId),
        toolCompiledPath(toolId),
        toolSchemaPath(toolId),
        toolCapabilitiesPath(toolId),
    ]) {
        if (await store.exists(revisionId, path)) {
            await store.delete(revisionId, path)
        }
    }
}

/**
 * Delete one skill's folder (`skills/<id>/` — SKILL.md plus any companion
 * files), so a re-PUT fully replaces the skill rather than leaving stale
 * companions behind.
 */
export async function deleteSkillFiles(revisionId: string, store: BundleStore, skillId: string): Promise<void> {
    const entries = await store.list(revisionId, `skills/${skillId}/`)
    for (const e of entries) {
        await store.delete(revisionId, e.path)
    }
}
