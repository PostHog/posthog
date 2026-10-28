import { describe, expect, test } from 'bun:test'
import { mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { contentHash, SymbolDataType, writeSymbolData } from '@/error-tracking/container'
import { runHog } from '@/testing'

import { GIT_REPO, SMALL_MAPPING } from '../../../test/parity/fixtures'

function project(files: Record<string, string>): string {
    const folder = mkdtempSync(join(tmpdir(), 'hog-et-'))
    for (const [path, contents] of Object.entries(files)) {
        mkdirSync(join(folder, path, '..'), { recursive: true })
        writeFileSync(join(folder, path), contents)
    }
    return folder
}

describe('hog error-tracking upload', () => {
    test.each([
        ['the map ID from posthog.json', [], 'map-1'],
        ['--map-id over the one in posthog.json', ['--map-id', 'map-2'], 'map-2'],
    ])('--dry-run plans uploads from posthog.json without credentials, with %s', async (_name, flags, chunkId) => {
        const folder = project({
            'posthog.json': JSON.stringify({
                errorTracking: {
                    release: { name: 'app', version: '2.0' },
                    sources: [{ path: 'build', mapId: 'map-1' }],
                },
            }),
            'build/mapping.txt': SMALL_MAPPING,
            'build/notes.txt': 'not a mapping',
        })
        const result = await runHog(['et', 'upload', '--dry-run', ...flags], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toEqual({
            dryRun: true,
            release: { name: 'app', version: '2.0', id: null },
            skipped: [],
            warnings: [],
            deletedMaps: [],
            symbolSets: [
                {
                    path: 'build/mapping.txt',
                    kind: 'proguard',
                    chunkId,
                    contentHash: contentHash(
                        writeSymbolData(SymbolDataType.ProguardMapping, Buffer.from(SMALL_MAPPING))
                    ),
                    size: expect.any(Number),
                    status: 'planned',
                },
            ],
        })
    })

    test('--dry-run leaves bundles and maps untouched, and ignore globs skip files', async () => {
        const bundle = 'a();\n//# sourceMappingURL=a.js.map\n'
        const map = JSON.stringify({ version: 3, sources: ['a.ts'], names: [], mappings: 'AAAA' })
        const folder = project({
            'posthog.json': JSON.stringify({ errorTracking: { sources: [{ path: 'dist', ignore: ['vendor/**'] }] } }),
            'dist/a.js': bundle,
            'dist/a.js.map': map,
            'dist/vendor/b.js': bundle.replace('a.js.map', 'b.js.map'),
            'dist/vendor/b.js.map': map,
        })
        const result = await runHog(['et', 'process', '--dry-run'], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })

        expect(result.exitCode).toBe(0)
        expect(result.json()).toMatchObject({
            dryRun: true,
            injected: [{ path: 'dist/a.js', action: 'injected' }],
            symbolSets: [{ path: 'dist/a.js', kind: 'js', status: 'planned' }],
        })
        expect(readFileSync(join(folder, 'dist/a.js'), 'utf8')).toBe(bundle)
        expect(readFileSync(join(folder, 'dist/a.js.map'), 'utf8')).toBe(map)
    })

    test('--dry-run reads the release from the repository a symlinked mapping points into', async () => {
        const repository = project({ ...GIT_REPO, 'app/mapping.txt': SMALL_MAPPING })
        const outside = project({})
        symlinkSync(join(repository, 'app/mapping.txt'), join(outside, 'mapping.txt'))
        const result = await runHog(['et', 'upload', '--dry-run', 'mapping.txt', '--map-id', 'map-1'], {
            env: { CLAUDECODE: '1' },
            cwd: outside,
            useDisk: true,
        })
        expect(result.json().release).toEqual({
            name: 'example-app',
            version: 'c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00',
            id: null,
        })
    })

    test.each([
        ['a ProGuard mapping without a map ID', ['mapping.txt'], 2, 'map_id_required'],
        ['a file hog cannot place', ['notes.txt'], 1, 'unknown_artifact'],
        ['no paths and no posthog.json', [], 2, 'no_paths'],
        ['--force with --skip-on-conflict', ['mapping.txt', '--force', '--skip-on-conflict'], 2, 'usage_error'],
        ['a concurrency below 1', ['mapping.txt', '--concurrency', '0'], 2, 'usage_error'],
    ])('%s fails with a hint', async (_name, paths, exitCode, code) => {
        const folder = project({ 'mapping.txt': SMALL_MAPPING, 'notes.txt': 'hello' })
        const result = await runHog(['et', 'upload', '--dry-run', ...paths], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })
        expect(result.exitCode).toBe(exitCode)
        expect(result.error()).toMatchObject({ code, hint: expect.any(String) })
    })
})
