// Generator for the MCP app-url manifest. It lives in the frontend because the only complete source
// of canonical PostHog routes is the merged `urls` object (scenes/urls.ts), which is
// `{ ...productUrls, <~80 builders defined directly here> }`. We derive each route template by
// *invoking* the real builder with `:name` sentinels — the same trick urls.ts itself uses
// (`href(':id')`) — instead of parsing function bodies. Running the shipped code means combineUrl,
// ternaries, and encodeURIComponent are handled correctly and the manifest can never silently drift
// from what the app actually renders.
//
// The output is consumed by the MCP `generate-app-url` tool so it never hand-builds (and mis-slugs)
// entity links. This module is pure — it takes `urls` and a scope oracle as arguments and pulls in
// no frontend runtime — so the generating test supplies them.

export type AppUrlScope = 'project' | 'global'

export interface AppUrlEntry {
    /** Relative path template with `{param}` placeholders, e.g. `/persons/{uuid}` (no host or project prefix). */
    template: string
    /** Placeholder names that appear in `template`, in declaration order. */
    params: string[]
    /** `project` paths get the `/project/:id` prefix; `global` paths (org/account/auth) get only the host. */
    scope: AppUrlScope
}

export type AppUrlManifest = Record<string, AppUrlEntry>

export interface AppUrlManifestBuildResult {
    manifest: AppUrlManifest
    /** Builders left out of the manifest entirely, with a reason — kept visible so coverage gaps don't hide. */
    excluded: { name: string; reason: string }[]
    /** Builders kept as base-path links because their params only affect query/hash, not the path. */
    baseOnly: string[]
}

// `urls` helpers that build prefixes/origins rather than linkable destinations.
const EXCLUDED_HELPERS = new Set(['absolute', 'default', 'project', 'currentProject', 'newTab'])

function sentinel(name: string): string {
    return `:${name}`
}

interface Signature {
    kind: 'positional' | 'object'
    names: string[]
}

function readSignature(fn: (...args: unknown[]) => unknown): Signature | null {
    const src = fn.toString().trim()
    // Single-param arrow without parens, e.g. `id => ...`.
    const single = src.match(/^(?:async\s+)?([A-Za-z_$][\w$]*)\s*=>/)
    if (single) {
        return { kind: 'positional', names: [single[1]] }
    }
    const paramStr = parenContents(src)
    if (paramStr === null) {
        return null
    }
    const trimmed = paramStr.trim()
    if (trimmed === '') {
        return { kind: 'positional', names: [] }
    }
    if (trimmed.startsWith('{')) {
        return { kind: 'object', names: [] }
    }
    const names = splitTopLevel(trimmed)
        .map((part) => part.trim().split(/[=:]/)[0].trim())
        .filter(Boolean)
    return { kind: 'positional', names }
}

// Contents of the first balanced `(...)` group — the parameter list of an arrow/function.
function parenContents(src: string): string | null {
    const start = src.indexOf('(')
    if (start === -1) {
        return null
    }
    let depth = 0
    for (let i = start; i < src.length; i++) {
        const ch = src[i]
        if (ch === '(') {
            depth++
        } else if (ch === ')') {
            depth--
            if (depth === 0) {
                return src.slice(start + 1, i)
            }
        }
    }
    return null
}

function splitTopLevel(input: string): string[] {
    const parts: string[] = []
    let depth = 0
    let current = ''
    for (const ch of input) {
        if (ch === '(' || ch === '[' || ch === '{') {
            depth++
        } else if (ch === ')' || ch === ']' || ch === '}') {
            depth--
        }
        if (ch === ',' && depth === 0) {
            parts.push(current)
            current = ''
        } else {
            current += ch
        }
    }
    if (current.trim()) {
        parts.push(current)
    }
    return parts
}

// Invoke the builder with the *fewest* sentinel args that yield a clean path, and return that path.
// Trying small first drops optional trailing params (a `tab`, `formMode`, query-only options) and hits
// guarded default branches (`replay()` -> `/replay/home`, `organizationBilling()` -> `/organization/billing`)
// instead of erroring on a sentinel.
function probeBuilder(fn: (...args: unknown[]) => unknown, signature: Signature): string | null {
    const maxArgs = signature.kind === 'object' ? 0 : signature.names.length
    for (let count = 0; count <= maxArgs; count++) {
        const args = signature.kind === 'object' ? [{}] : signature.names.slice(0, count).map(sentinel)
        let raw: unknown
        try {
            raw = fn(...args)
        } catch {
            continue
        }
        if (typeof raw !== 'string') {
            continue
        }
        const path = raw.split('?')[0].split('#')[0]
        // Reject `/`, non-paths, and paths where an omitted arg was interpolated as undefined/null —
        // that means this arg count is too small and the builder genuinely needs more.
        if (!path.startsWith('/') || path === '/' || path.includes('undefined') || path.includes('null')) {
            continue
        }
        return path
    }
    return null
}

function replaceSentinels(path: string, paramNames: string[]): { template: string; params: string[] } {
    let template = path
    const found = new Set<string>()
    // Longest names first so `:id` never partially clobbers `:insightId` etc.
    for (const name of [...paramNames].sort((a, b) => b.length - a.length)) {
        const encoded = encodeURIComponent(sentinel(name)) // `:id` -> `%3Aid` for builders that encodeURIComponent
        const plain = sentinel(name) // `:id` for builders that interpolate raw
        const before = template
        template = template.split(encoded).join(`{${name}}`).split(plain).join(`{${name}}`)
        if (template !== before) {
            found.add(name)
        }
    }
    // Keep declaration order for stable, readable output.
    return { template, params: paramNames.filter((name) => found.has(name)) }
}

export function buildAppUrlManifest(
    urls: Record<string, unknown>,
    isProjectScoped: (template: string) => boolean
): AppUrlManifestBuildResult {
    const manifest: AppUrlManifest = {}
    const excluded: { name: string; reason: string }[] = []
    const baseOnly: string[] = []

    for (const name of Object.keys(urls).sort()) {
        if (EXCLUDED_HELPERS.has(name)) {
            excluded.push({ name, reason: 'structural helper (prefix/origin), not a destination' })
            continue
        }
        const fn = urls[name]
        if (typeof fn !== 'function') {
            excluded.push({ name, reason: 'not a function' })
            continue
        }
        const signature = readSignature(fn as (...args: unknown[]) => unknown)
        if (!signature) {
            excluded.push({ name, reason: 'could not parse signature' })
            continue
        }

        const probePath = probeBuilder(fn as (...args: unknown[]) => unknown, signature)
        if (!probePath) {
            excluded.push({ name, reason: 'no argument count produced a clean path (only query/optional params?)' })
            continue
        }

        // Map against the full signature, not just the args we supplied: a builder whose default value
        // is itself a sentinel (e.g. `accountConnected: (kind = ':kind')`) emits `:kind` even at zero
        // args, and replaceSentinels only rewrites tokens that actually appear, so this stays correct.
        const { template, params } = replaceSentinels(probePath, signature.names)
        manifest[name] = { template, params, scope: isProjectScoped(template) ? 'project' : 'global' }

        const acceptsArgs = signature.kind === 'object' || signature.names.length > 0
        if (acceptsArgs && params.length === 0) {
            baseOnly.push(name)
        }
    }

    return { manifest, excluded, baseOnly }
}
