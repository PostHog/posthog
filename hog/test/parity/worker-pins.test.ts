import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const REPOSITORY = join(import.meta.dir, '..', '..', '..')
const EXACT = '='

interface Manifest {
    dependencies: Record<string, string | { version?: string }>
}

interface Lockfile {
    package: { name: string; version: string }[]
}

const readToml = <T>(path: string): T => Bun.TOML.parse(readFileSync(join(REPOSITORY, path), 'utf8')) as T

// hog-worker copies posthog-cli's byte-deciding code, so the crates that code calls must resolve to
// the versions posthog-cli builds with. A bump on one side fails here until the other follows.
describe('hog-worker pins the crates posthog-cli resolves', () => {
    const manifest = readToml<Manifest>('hog/worker/Cargo.toml')
    const lockfile = readToml<Lockfile>('cli/Cargo.lock')
    const pinned = Object.entries(manifest.dependencies).flatMap(([name, spec]) => {
        const version = typeof spec === 'string' ? spec : spec.version
        return version?.startsWith(EXACT) ? [[name, version.slice(EXACT.length)] as const] : []
    })

    test('some crates are pinned', () => {
        expect(pinned.length).toBeGreaterThan(0)
    })

    test.each(pinned)('%s %s', (name, version) => {
        const resolved = lockfile.package.filter((entry) => entry.name === name).map((entry) => entry.version)

        expect(resolved).toContain(version)
    })
})
