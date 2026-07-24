#!/usr/bin/env node
// Print the directories (repo-relative, one per line) of workspace packages that
// @posthog/frontend transitively depends on and that define a `build` script —
// i.e. the packages turbo's `^build` would run before `start-vite`. bin/start-frontend
// uses this set to decide whether the turbo build step can be skipped: if none of
// these directories changed since the last successful build, turbo is a ~2s no-op.
import { existsSync, readFileSync, realpathSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const frontendDir = join(repoRoot, 'frontend')

const seen = new Set()
const buildDirs = []

function visit(pkgDir, isRoot) {
    const real = realpathSync(pkgDir)
    if (seen.has(real)) {
        return
    }
    seen.add(real)
    const pkg = JSON.parse(readFileSync(join(real, 'package.json'), 'utf8'))
    if (!isRoot && pkg.scripts?.build) {
        buildDirs.push(real)
    }
    for (const [name, spec] of Object.entries({ ...pkg.dependencies, ...pkg.devDependencies })) {
        if (!String(spec).startsWith('workspace:')) {
            continue
        }
        // pnpm links workspace deps into the package's node_modules
        const dir = join(real, 'node_modules', name)
        if (existsSync(dir)) {
            visit(dir, false)
        }
    }
}

visit(frontendDir, true)
console.info(
    buildDirs
        .map((d) => relative(repoRoot, d))
        .sort()
        .join('\n')
)
