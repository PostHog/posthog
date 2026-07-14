#!/usr/bin/env node
import { spawn } from 'node:child_process'
import { existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
// Regenerate vite.deps.json — the committed snapshot of the dependencies Vite pre-bundles on a
// cold start. Runs Vite's own dependency discovery (a real scan) against the current source, then
// records the discovered set together with a fingerprint of the dependency closure. On a normal
// cold start Vite can then skip the scan whenever the fingerprint still matches.
//
// Run after adding/removing/bumping frontend dependencies: `pnpm vite:deps`.
import { createRequire } from 'node:module'
import { dirname, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const metadataPath = resolve(frontendDir, 'node_modules/.vite/deps/_metadata.json')
const outputPath = resolve(frontendDir, 'vite.deps.json')

// Reuse the same fingerprint logic the config uses so the two never drift (Node strips the types).
const { computeDepsFingerprint } = await import('../plugins/vite-deps-cache.ts')

async function main() {
    rmSync(resolve(frontendDir, 'node_modules/.vite'), { recursive: true, force: true })

    const vite = spawn(resolve(frontendDir, 'node_modules/.bin/vite'), ['--host', '127.0.0.1'], {
        cwd: frontendDir,
        env: { ...process.env, VITE_DEPS_REGEN: '1' },
        stdio: ['ignore', 'pipe', 'inherit'],
    })

    let ready = false
    vite.stdout.on('data', (chunk) => {
        process.stdout.write(chunk)
        if (!ready && chunk.toString().includes('ready in')) {
            ready = true
            // Trigger dependency discovery by loading the entry graph.
            fetch('http://127.0.0.1:8234/').catch(() => {})
            fetch('http://127.0.0.1:8234/src/index.tsx').catch(() => {})
        }
    })

    // Poll for the optimizer to finish writing its metadata.
    const deadline = Date.now() + 120_000
    while (Date.now() < deadline) {
        if (existsSync(metadataPath)) {
            await new Promise((r) => setTimeout(r, 1500)) // let the optimizer settle
            break
        }
        await new Promise((r) => setTimeout(r, 200))
    }

    vite.kill('SIGTERM')

    if (!existsSync(metadataPath)) {
        console.error('❌ Vite never produced a dependency metadata file — aborting.')
        process.exit(1)
    }

    const metadata = JSON.parse(readFileSync(metadataPath, 'utf8'))
    const optimized = metadata.optimized ?? {}
    const include = Object.keys(optimized).sort()
    if (include.length === 0) {
        console.error('❌ No dependencies were discovered — aborting.')
        process.exit(1)
    }

    // Deps that don't resolve as bare specifiers from the frontend root (they belong to products/*
    // workspace packages) need an explicit alias to their package directory, or the optimizer can't
    // pre-bundle them under noDiscovery. Vite records each dep's resolved module path in the
    // metadata; derive the package dir from it and store it relative to the frontend dir.
    const require = createRequire(resolve(frontendDir, 'package.json'))
    const depsDir = resolve(frontendDir, 'node_modules/.vite/deps')
    const aliases = {}
    for (const name of include) {
        try {
            require.resolve(name)
            continue // resolvable from the frontend root — no alias needed
        } catch {
            // fall through
        }
        const src = optimized[name]?.src
        if (!src) {
            continue
        }
        const abs = resolve(depsDir, src)
        // Cut the path back to the package root: .../node_modules/<name>
        const marker = `${sep}node_modules${sep}${name.split('/').join(sep)}`
        const idx = abs.lastIndexOf(marker)
        if (idx === -1) {
            continue
        }
        aliases[name] = relative(frontendDir, abs.slice(0, idx + marker.length))
    }

    const snapshot = { fingerprint: computeDepsFingerprint(frontendDir), include, aliases }
    writeFileSync(outputPath, JSON.stringify(snapshot, null, 4) + '\n')
    console.info(
        `✅ Wrote ${include.length} pre-bundled deps (${Object.keys(aliases).length} aliased) to vite.deps.json`
    )
    process.exit(0)
}

main().catch((err) => {
    console.error(err)
    process.exit(1)
})
