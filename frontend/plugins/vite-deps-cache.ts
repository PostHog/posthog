import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// Committed snapshot of the dependencies Vite pre-bundles on a cold start, plus a fingerprint
// of the dependency closure it was generated against. When the fingerprint still matches, the
// snapshot is provably complete, so we can hand it to Vite as an explicit `optimizeDeps.include`
// list and set `noDiscovery: true` — skipping the ~3s cold-start dependency scan that crawls the
// entire first-party module graph just to rediscover the same set.
//
// When the fingerprint does NOT match (a dependency was added/removed/bumped), we fall back to
// Vite's normal scan-based discovery, so a stale snapshot is never worse than no snapshot. Run
// `pnpm vite:deps` to regenerate it after changing dependencies.

const DEPS_FILE = 'vite.deps.json'
// Files whose contents define the frontend dependency closure. The lockfile uniquely determines
// every resolved dependency (a package.json dep change always updates it), so hashing package.json
// itself would only cause false invalidations from script edits.
const FINGERPRINT_FILES = ['../pnpm-lock.yaml', '../pnpm-workspace.yaml']

export interface ViteDepsSnapshot {
    fingerprint: string
    include: string[]
    // Deps that Vite discovered through the source graph but that don't resolve as bare specifiers
    // from the frontend root (they belong to `products/*` workspace packages). Mapping each to its
    // resolved module path (relative to the frontend dir) lets the optimizer pre-bundle them under
    // `noDiscovery`; without it a CommonJS one would be served raw and break in the browser.
    aliases: Record<string, string>
    // Every include specifier mapped to the module file (relative to the frontend dir) Vite
    // resolved it to when the snapshot was generated. The optimizer re-resolves every include
    // specifier sequentially on each cold start (~1s for 230 specifiers); replaying these through
    // an exact-match alias entry skips that. Fingerprint-gated like the rest of the snapshot.
    resolved: Record<string, string>
}

export interface PrebundledDeps {
    include: string[]
    aliases: Record<string, string>
    resolved: Record<string, string>
}

export function computeDepsFingerprint(root: string): string {
    const hash = createHash('sha256')
    for (const rel of FINGERPRINT_FILES) {
        const path = resolve(root, rel)
        hash.update(rel)
        hash.update(existsSync(path) ? readFileSync(path) : Buffer.alloc(0))
    }
    return hash.digest('hex')
}

export function depsFilePath(root: string): string {
    return resolve(root, DEPS_FILE)
}

// Returns the committed pre-bundle set only when its fingerprint matches the current dependency
// closure; otherwise null so the caller keeps Vite's default discovery.
export function loadPrebundledDeps(root: string): PrebundledDeps | null {
    const path = depsFilePath(root)
    if (!existsSync(path)) {
        return null
    }
    try {
        const snapshot = JSON.parse(readFileSync(path, 'utf8')) as ViteDepsSnapshot
        if (snapshot.fingerprint !== computeDepsFingerprint(root)) {
            return null
        }
        return { include: snapshot.include, aliases: snapshot.aliases ?? {}, resolved: snapshot.resolved ?? {} }
    } catch {
        return null
    }
}
