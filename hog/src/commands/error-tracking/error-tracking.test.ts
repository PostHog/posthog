import { describe, expect, test } from 'bun:test'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { cleanUp, cssTargets } from '@/error-tracking/cleanup'
import { contentHash, SymbolDataType, writeSymbolData } from '@/error-tracking/container'
import { stripCredentials } from '@/error-tracking/git'
import { loadMapContent, serializeMapContent } from '@/error-tracking/kinds/js'
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

    const MAP = JSON.stringify({ version: 3, sources: ['a.ts'], names: [], mappings: 'AAAA' })
    test.each([
        [
            'a reference to a JSON file that is not a sourcemap',
            { 'dist/a.js': 'a();\n//# sourceMappingURL=../settings.json\n', 'settings.json': '{"theme":"dark"}' },
            [],
            'settings.json',
            "isn't a sourcemap",
        ],
        [
            'a sourcemap that matches an ignore pattern',
            { 'dist/a.js': 'a();\n//# sourceMappingURL=a.js.map\n', 'dist/a.js.map': MAP },
            ['a.js.map'],
            'dist/a.js.map',
            'ignore pattern',
        ],
    ])('inject skips %s and leaves it alone', async (_name, files, ignore, untouched, reason) => {
        const folder = project({
            'posthog.json': JSON.stringify({ errorTracking: { sources: [{ path: 'dist', ignore }] } }),
            'dist/b.js': 'b();\n//# sourceMappingURL=b.js.map\n',
            'dist/b.js.map': MAP,
            ...files,
        })
        const before = readFileSync(join(folder, untouched), 'utf8')
        const result = await runHog(['et', 'inject'], { env: { CLAUDECODE: '1' }, cwd: folder, useDisk: true })

        expect(result.exitCode).toBe(0)
        expect(result.json().skipped).toEqual([
            { path: expect.stringMatching(/dist\/a\.js$/), reason: expect.stringContaining(reason) },
        ])
        expect(readFileSync(join(folder, untouched), 'utf8')).toBe(before)
    })

    test('--delete-after leaves maps outside the selected paths, and skips unreadable CSS references', () => {
        const bundle = 'a();\n//# sourceMappingURL=../maps/a.js.map\n'
        const stylesheet = 'a{}\n/*# sourceMappingURL=%FF.css.map */\n'
        const folder = project({ 'dist/a.js': bundle, 'maps/a.js.map': MAP, 'dist/site.css': stylesheet })
        const warnings: string[] = []
        const outside = {
            sourcePath: join(folder, 'dist/a.js'),
            mapPath: join(folder, 'maps/a.js.map'),
            sourceFingerprint: contentHash(bundle),
            mapFingerprint: contentHash(serializeMapContent(loadMapContent(MAP))),
            kind: 'js' as const,
        }
        const css = cssTargets([join(folder, 'dist/site.css')], undefined, warnings)
        const result = cleanUp([outside, ...css], [join(folder, 'dist')])

        expect(result.deletedMaps).toEqual([])
        expect([...warnings, ...result.warnings]).toEqual([
            expect.stringContaining("site.css: its sourcemap reference can't be read"),
            expect.stringContaining('resolves outside the selected paths'),
        ])
        expect(existsSync(join(folder, 'maps/a.js.map'))).toBe(true)
        expect(readFileSync(join(folder, 'dist/a.js'), 'utf8')).toBe(bundle)
    })

    test.skipIf(process.getuid?.() === 0)('inject changes no bundle when a map cannot be written', async () => {
        const bundle = 'a();\n//# sourceMappingURL=a.js.map\n'
        const folder = project({ 'dist/a.js': bundle, 'dist/a.js.map': MAP })
        chmodSync(join(folder, 'dist/a.js.map'), 0o444)
        const result = await runHog(['et', 'inject', 'dist'], { env: { CLAUDECODE: '1' }, cwd: folder, useDisk: true })

        expect(result.exitCode).toBe(1)
        expect(readFileSync(join(folder, 'dist/a.js'), 'utf8')).toBe(bundle)
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
        ['git@github.com:org/repo.git', 'git@github.com:org/repo.git'],
        ['ghp_token@github.com:org/repo.git', 'github.com:org/repo.git'],
        ['https://x-access-token:secret@github.com/org/repo.git', 'https://github.com/org/repo.git'],
        ['git@github.com:org/repo@secret.git', undefined],
    ])('the release keeps no credential from the remote %s', (remote, stored) => {
        expect(stripCredentials(remote)).toBe(stored)
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
