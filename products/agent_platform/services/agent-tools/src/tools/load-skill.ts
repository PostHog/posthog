/**
 * `@posthog/load-skill` — fetches a skill's `SKILL.md` body, or a companion
 * file within the skill folder, on demand. A skill is one of two sources
 * (declared on its `spec.skills[]` entry):
 *   - `bundle` (default): shipped in the agent's own bundle at `path`; read via
 *     `ctx.readBundleFile`.
 *   - `store`: referenced via `skill_refs`, NOT in the bundle; resolved LIVE
 *     from the PostHog skill store via `ctx.resolveStoreSkill` (latest, or the
 *     pinned `version`). A store edit shows up on the next load.
 *
 * The runner builds the system prompt with a one-line index of available
 * skills (`- <id>: <description>`); the model calls this tool only when it
 * actually needs the content. Cheaper than inlining every skill into every
 * prompt. Per the Agent Skills progressive-disclosure model, a `SKILL.md`
 * body can point at companion files under `references/`, `scripts/`,
 * `assets/` (or any nested path); the model loads those on demand by passing
 * `file`.
 *
 * Auto-included by the runner when `spec.skills` is non-empty.
 */

import { defineNativeTool, Type } from '@posthog/agent-shared'

/**
 * Validate a model-chosen companion `file` stays inside its skill's folder —
 * reject absolute paths, `..`/`.` traversal, and empty segments. Returns the
 * normalized relative path. Shared by the bundle resolver and the store branch.
 */
export function assertSafeCompanion(file: string): string {
    const rel = file.replace(/\\/g, '/')
    if (rel.startsWith('/')) {
        throw new Error(`load-skill: file "${file}" must be a relative path inside the skill folder.`)
    }
    const segments = rel.split('/')
    if (segments.some((s) => s === '..' || s === '.' || s === '')) {
        throw new Error(`load-skill: file "${file}" must not contain traversal or empty segments.`)
    }
    return rel
}

/**
 * Resolve a companion-file path relative to a bundle skill's directory.
 *
 * `skillPath` is the SKILL.md entry path (`skills/<alias>/SKILL.md`); the
 * skill root is its directory. `file` is rejected if it escapes that root
 * (absolute, `..` traversal, or empty segment) — companion files must stay
 * inside the skill folder.
 */
export function resolveSkillFile(skillPath: string, file: string): string {
    // Companion files only exist in the spec's directory layout
    // (`skills/<alias>/SKILL.md` + siblings), where the skill owns its folder.
    // A legacy flat skill (`skills/<alias>.md`) has no folder of its own — its
    // directory is the shared `skills/` root — so a model-chosen `file` there
    // could read a *different* skill's files. Reject companion reads unless the
    // path is the `…/SKILL.md` shape, and scope `file` to that skill's folder.
    const lastSlash = skillPath.lastIndexOf('/')
    if (lastSlash === -1 || skillPath.slice(lastSlash + 1) !== 'SKILL.md') {
        throw new Error(`load-skill: skill "${skillPath}" has no companion files.`)
    }
    const root = skillPath.slice(0, lastSlash) // the skill's own folder
    return `${root}/${assertSafeCompanion(file)}`
}

export const loadSkill = defineNativeTool({
    id: '@posthog/load-skill',
    description:
        'Fetch the body of a skill from this agent\'s bundle. Use the `id` from the "Available skills" index in the system prompt. Pass `file` to fetch a companion file inside the skill folder (e.g. `references/api.md`, `scripts/run.py`) when the skill body points at one. Returns the content; treat a skill body as additional instructions for the current task.',
    args: Type.Object({
        id: Type.String({ minLength: 1, description: 'Skill id from the system prompt index.' }),
        file: Type.Optional(
            Type.String({
                minLength: 1,
                description:
                    "Optional companion file path relative to the skill folder. Omit to load the skill's SKILL.md body.",
            })
        ),
    }),
    returns: Type.Object({
        id: Type.String(),
        path: Type.String(),
        body: Type.String(),
    }),
    requires: {},
    cost_hint: 'cheap',
    async run(args, ctx) {
        if (!ctx.skillIndex) {
            throw new Error('load-skill: runner did not wire skill access (skillIndex)')
        }
        const entry = ctx.skillIndex.find((s) => s.id === args.id)
        if (!entry) {
            throw new Error(
                `load-skill: unknown skill id "${args.id}". Available: ${ctx.skillIndex.map((s) => s.id).join(', ') || '(none)'}`
            )
        }

        // Store skills carry no bundle bytes — resolve them live from the skill
        // store by their store name (`from_template`), at the pinned `version`
        // or latest. The synthetic `store://…` path is informational (return +
        // logs); the model addresses companion files by the same `file` arg.
        if (entry.source === 'store') {
            if (!ctx.resolveStoreSkill) {
                throw new Error('load-skill: runner did not wire store-skill access (resolveStoreSkill)')
            }
            const name = entry.from_template ?? entry.id
            if (args.file !== undefined) {
                assertSafeCompanion(args.file)
            }
            const pin = entry.version !== undefined ? `@${entry.version}` : '@latest'
            const path = args.file ? `store://${name}${pin}/${args.file}` : `store://${name}${pin}`
            let body: string | null
            try {
                body = await ctx.resolveStoreSkill(name, entry.version, args.file)
            } catch (err) {
                // resolveStoreSkill returns null for a genuinely-absent
                // skill/version/file and throws only on an operational DB
                // failure — surface that as retryable, not a permanent miss.
                const reason = err instanceof Error ? err.message : String(err)
                throw new Error(
                    `load-skill: transient error resolving store skill "${args.id}" (${reason}). Retry the call.`
                )
            }
            if (body === null) {
                const what = args.file ? `file "${args.file}" ` : ''
                throw new Error(`load-skill: store skill "${args.id}" ${what}not found in the skill store`)
            }
            ctx.log('info', 'skill.loaded', { id: args.id, path, source: 'store', bytes: body.length })
            return { id: args.id, path, body }
        }

        // Bundle skills (the default): read the SKILL.md (or a companion) from
        // the active revision's bundle.
        if (!ctx.readBundleFile) {
            throw new Error('load-skill: runner did not wire bundle access (readBundleFile)')
        }
        if (!entry.path) {
            throw new Error(`load-skill: bundle skill "${args.id}" has no bundle path`)
        }
        const path = args.file ? resolveSkillFile(entry.path, args.file) : entry.path
        let body: string | null
        try {
            body = await ctx.readBundleFile(path)
        } catch (err) {
            // readBundleFile returns null for a genuinely-absent file and only
            // throws on an operational read failure (transient store error,
            // auth, network). Surface that as retryable instead of a permanent
            // "not found" so the model tries again rather than proceeding blind.
            const reason = err instanceof Error ? err.message : String(err)
            throw new Error(`load-skill: transient error reading skill "${args.id}" (${reason}). Retry the call.`)
        }
        if (body === null) {
            throw new Error(`load-skill: skill "${args.id}" path "${path}" not found in the bundle`)
        }
        ctx.log('info', 'skill.loaded', { id: args.id, path, source: 'bundle', bytes: body.length })
        return { id: args.id, path, body }
    },
})
