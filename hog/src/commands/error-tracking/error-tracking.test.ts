import { describe, expect, test } from 'bun:test'
import {
    chmodSync,
    cpSync,
    existsSync,
    mkdirSync,
    mkdtempSync,
    readFileSync,
    rmSync,
    symlinkSync,
    writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { cleanUp, cssTargets } from '@/error-tracking/cleanup'
import { contentHash, SymbolDataType, writeSymbolData } from '@/error-tracking/container'
import { runHog } from '@/testing'

import { GIT_REPO, SMALL_MAPPING } from '../../../test/parity/fixtures'
import { HERMES_BUILD } from '../../../test/parity/hermes-fixtures'

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

    test('--delete-after leaves alone CSS maps outside the selected paths, ignored maps, and JSON that is not a map', () => {
        const folder = project({
            'dist/broken.css': 'a{}\n/*# sourceMappingURL=%FF.css.map */\n',
            'dist/outside.css': 'a{}\n/*# sourceMappingURL=../maps/outside.css.map */\n',
            'maps/outside.css.map': MAP,
            'dist/settings.css': 'a{}\n/*# sourceMappingURL=settings.json */\n',
            'dist/settings.json': '{"theme":"dark"}',
            'dist/ignored.css': 'a{}\n/*# sourceMappingURL=ignored.css.map */\n',
            'dist/ignored.css.map': MAP,
            'dist/kept.css': 'a{}\n/*# sourceMappingURL=kept.css.map */\n',
            'dist/kept.css.map': MAP,
        })
        const warnings: string[] = []
        const css = cssTargets(
            ['broken', 'outside', 'settings', 'ignored', 'kept'].map((name) => join(folder, `dist/${name}.css`)),
            [join(folder, 'dist')],
            undefined,
            warnings,
            (mapPath) => mapPath.endsWith('ignored.css.map')
        )
        const result = cleanUp(css)

        expect(result.deletedMaps).toEqual([expect.stringMatching(/dist\/kept\.css\.map$/)])
        expect(warnings).toEqual([
            expect.stringContaining("broken.css: its sourcemap reference can't be read"),
            expect.stringContaining('resolves outside the selected paths'),
        ])
        for (const path of ['maps/outside.css.map', 'dist/settings.json', 'dist/ignored.css.map']) {
            expect(existsSync(join(folder, path))).toBe(true)
        }
    })

    test.skipIf(process.getuid?.() === 0)('inject changes no bundle when a map cannot be written', async () => {
        const bundle = 'a();\n//# sourceMappingURL=a.js.map\n'
        const folder = project({ 'dist/a.js': bundle, 'dist/a.js.map': MAP })
        chmodSync(join(folder, 'dist/a.js.map'), 0o444)
        const result = await runHog(['et', 'inject', 'dist'], { env: { CLAUDECODE: '1' }, cwd: folder, useDisk: true })

        expect(result.exitCode).toBe(1)
        expect(readFileSync(join(folder, 'dist/a.js'), 'utf8')).toBe(bundle)
    })

    test('--dry-run plans a Hermes map once when two paths overlap', async () => {
        const composed = 'android/hbc/index.android.bundle.hbc.composed.map'
        const folder = project({
            ...HERMES_BUILD,
            [composed]: HERMES_BUILD[composed]!.replace('{', '{"chunk_id":"0b9f3c55-6a1e-4f43-9d9a-3a1f2c7e8b10",'),
        })
        const result = await runHog(['et', 'upload', '--dry-run', 'android', 'android/hbc'], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })
        expect(result.exitCode).toBe(0)
        expect(result.json().symbolSets).toEqual([expect.objectContaining({ path: composed, kind: 'hermes' })])
    })

    test('upload fails when Hermes bundles have no composed maps', async () => {
        const { 'android/hbc/index.android.bundle.hbc.composed.map': _composed, ...metroOnly } = HERMES_BUILD
        const folder = project(metroOnly)
        const result = await runHog(['et', 'upload', '--dry-run', 'android'], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })
        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code: 'no_hermes_maps' })
    })

    const NATIVE = join(import.meta.dir, '../../../test/parity/native/bin')
    // A 64-bit Mach-O whose LC_UUID command claims a size of 0, which never advances to the next one.
    const header = Buffer.alloc(32)
    header.writeUInt32LE(0xfeedfacf, 0)
    header.writeUInt32LE(0x0100000c, 4)
    header.writeUInt32LE(0x6, 12)
    header.writeUInt32LE(2, 16)
    header.writeUInt32LE(48, 20)
    const uuidCommand = Buffer.alloc(24, 0xab)
    uuidCommand.writeUInt32LE(0x1b, 0)
    uuidCommand.writeUInt32LE(0, 4)
    const ZERO_CMDSIZE = Buffer.concat([header, uuidCommand, Buffer.alloc(24)])

    test.each([
        [
            'other uploads go ahead when no native file is usable',
            readFileSync(join(NATIVE, 'linux/checkout-no-debug')),
            ['mapping.txt', '--map-id', 'map-1'],
            0,
            'map-1',
        ],
        [
            'the failure names every skipped native file',
            readFileSync(join(NATIVE, 'linux/checkout-no-debug')),
            [],
            1,
            'bin/native: ',
        ],
        ['a Mach-O load command smaller than its header is skipped', ZERO_CMDSIZE, [], 1, 'smaller than its header'],
    ])('upload: %s', async (_name, binary, paths, exitCode, expected) => {
        const folder = project({ 'mapping.txt': SMALL_MAPPING })
        mkdirSync(join(folder, 'bin'))
        writeFileSync(join(folder, 'bin/native'), binary)
        const result = await runHog(['et', 'upload', '--dry-run', 'bin', ...paths], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })
        expect(result.exitCode).toBe(exitCode)
        expect(exitCode === 0 ? JSON.stringify(result.json().symbolSets) : result.error().message).toContain(expected)
    })

    test.each([
        ['skips a dSYM member that matches an ignore glob', ['Shop.app.dSYM/Contents/Resources/DWARF/**'], false],
        ['follows a dSYM member that is a symlink, as posthog-cli does', [], true],
    ])('upload %s', async (_name, ignore, linkOutside) => {
        const folder = project({
            'posthog.json': JSON.stringify({ errorTracking: { sources: [{ path: 'apple', ignore }] } }),
        })
        cpSync(join(NATIVE, 'apple/Shop.app.dSYM'), join(folder, 'apple/Shop.app.dSYM'), { recursive: true })
        if (linkOutside) {
            const member = join(folder, 'apple/Shop.app.dSYM/Contents/Resources/DWARF/Shop')
            cpSync(member, join(folder, 'outside/Shop'))
            rmSync(member)
            symlinkSync(join(folder, 'outside/Shop'), member)
        }
        const result = await runHog(['et', 'upload', '--dry-run'], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })

        if (linkOutside) {
            expect(result.exitCode).toBe(0)
            expect(result.json().symbolSets).toEqual([
                expect.objectContaining({ path: 'apple/Shop.app.dSYM', status: 'planned' }),
            ])
        } else {
            expect(result.exitCode).toBe(1)
            expect(result.error()).toMatchObject({
                code: 'no_debug_symbols',
                message: expect.stringContaining('apple/Shop.app.dSYM: '),
            })
        }
    })

    test('--include-source leaves out sources that match an ignore glob, also through a symlinked root', async () => {
        // The fixture's DWARF names its sources under this folder.
        const sources = '/tmp/hog-parity-native'
        rmSync(sources, { recursive: true, force: true })
        cpSync(join(NATIVE, '../src'), sources, { recursive: true })
        cpSync(join(NATIVE, 'linux/checkout'), join(sources, 'bin/checkout'))
        const plan = async (ignore: string[], linked = false): Promise<string> => {
            const folder = project({})
            if (linked) {
                symlinkSync(sources, join(folder, 'linked'))
            }
            const path = linked ? 'linked' : sources
            writeFileSync(
                join(folder, 'posthog.json'),
                JSON.stringify({ errorTracking: { sources: [{ path, ignore }] } })
            )
            const result = await runHog(['et', 'upload', '--dry-run', '--include-source'], {
                env: { CLAUDECODE: '1' },
                cwd: folder,
                useDisk: true,
            })
            expect(result.exitCode).toBe(0)
            return result.json().symbolSets[0].contentHash
        }
        try {
            const all = await plan([])
            rmSync(join(sources, 'checkout.c'))
            const withoutCheckout = await plan([])
            cpSync(join(NATIVE, '../src/checkout.c'), join(sources, 'checkout.c'))

            expect(withoutCheckout).not.toBe(all)
            expect(await plan(['checkout.c'])).toBe(withoutCheckout)
            expect(await plan(['checkout.c'], true)).toBe(withoutCheckout)
        } finally {
            rmSync(sources, { recursive: true, force: true })
        }
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
