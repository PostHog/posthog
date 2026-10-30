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
import { nativeCandidates } from '@/error-tracking/native/package'
import { ZipWriter } from '@/error-tracking/native/zip'
import { deriveBaseName } from '@/error-tracking/symbols'
import { runHog, TEST_CREDENTIALS } from '@/testing'

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

    test('--dry-run leaves bundles and maps untouched, ignore globs skip files, and unreadable folders are skipped', async () => {
        const bundle = 'a();\n//# sourceMappingURL=a.js.map\n'
        const map = JSON.stringify({ version: 3, sources: ['a.ts'], names: [], mappings: 'AAAA' })
        const folder = project({
            'posthog.json': JSON.stringify({ errorTracking: { sources: [{ path: 'dist', ignore: ['vendor/**'] }] } }),
            'dist/a.js': bundle,
            'dist/a.js.map': map,
            'dist/vendor/b.js': bundle.replace('a.js.map', 'b.js.map'),
            'dist/vendor/b.js.map': map,
            'dist/vendor/cache/c.js': bundle,
        })
        chmodSync(join(folder, 'dist/vendor/cache'), 0o000)

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

    test.each([
        ['HOG_RELEASE_MODE', { HOG_RELEASE_MODE: 'symbol-set' }, {}],
        ['errorTracking.releaseMode in posthog.json', {}, { releaseMode: 'symbol-set' }],
    ])('%s picks symbol-set mode, which mints random chunk IDs', async (_name, env, errorTracking) => {
        const folder = project({
            'posthog.json': JSON.stringify({
                errorTracking: { release: { name: 'app', version: '1' }, ...errorTracking },
            }),
            'dist/a.js': 'a();\n//# sourceMappingURL=a.js.map\n',
            'dist/a.js.map': JSON.stringify({ version: 3, sources: ['a.ts'], names: [], mappings: 'AAAA' }),
        })
        const result = await runHog(['et', 'process', 'dist', '--dry-run'], {
            env: { CLAUDECODE: '1', ...env },
            cwd: folder,
            useDisk: true,
        })
        expect(result.json().symbolSets).toEqual([
            expect.objectContaining({ chunkId: expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-7/) }),
        ])
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

    test('a universal binary with a slice that does not parse keeps its other slices', () => {
        const slice = readFileSync(join(import.meta.dir, '../../../test/parity/native/bin/apple/Shop.dwarf'))
        const header = Buffer.alloc(48)
        header.writeUInt32BE(0xcafebabe, 0)
        header.writeUInt32BE(2, 4)
        const arches: [number, number, number][] = [
            [0x0100000c, 4096, slice.length],
            [0x01000007, 4096 + slice.length, 8],
        ]
        for (const [index, [cputype, offset, size]] of arches.entries()) {
            header.writeUInt32BE(cputype, 8 + index * 20)
            header.writeUInt32BE(offset, 16 + index * 20)
            header.writeUInt32BE(size, 20 + index * 20)
        }
        const folder = project({})
        const path = join(folder, 'Shop')
        writeFileSync(path, Buffer.concat([header, Buffer.alloc(4096 - 48), slice, Buffer.alloc(8)]))

        const candidates = nativeCandidates(path)

        expect(candidates).toEqual([
            { file: expect.objectContaining({ format: 'macho', debugId: expect.any(String) }) },
            { path, problem: 'unparseable_slice' },
        ])
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

    function dsymWithBadChecksum(): Buffer {
        const zip = new ZipWriter()
        zip.add('dwarf', Buffer.from('not really dwarf, but bytes all the same'))
        const archive = zip.finish()
        const central = archive.indexOf(Buffer.from([0x50, 0x4b, 0x01, 0x02]))
        archive.writeUInt32LE((archive.readUInt32LE(central + 16) ^ 1) >>> 0, central + 16)
        return writeSymbolData(SymbolDataType.AppleDsym, archive)
    }

    test.each([
        ['a zip entry whose checksum is wrong', dsymWithBadChecksum, "doesn't match its recorded size and checksum"],
        [
            'a Hermes map that is not UTF-8, by its type rather than as unknown',
            () => writeSymbolData(SymbolDataType.HermesMap, Buffer.from([0xff, 0xfe])),
            'HermesMap whose payload',
        ],
    ])('extract rejects %s', async (_name, build, message) => {
        const folder = project({})
        writeFileSync(join(folder, 'Shop.dSYM'), build())
        const result = await runHog(['et', 'extract', 'Shop.dSYM'], {
            env: { CLAUDECODE: '1' },
            cwd: folder,
            useDisk: true,
        })
        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code: 'invalid_symbol_set', message: expect.stringContaining(message) })
    })

    test('extract escapes control characters in the file names it prints', async () => {
        const zip = new ZipWriter()
        zip.add('evil\u001b]52;c;cGF5\u0007', Buffer.from('dwarf'))
        const folder = project({})
        writeFileSync(join(folder, 'Shop.dSYM'), writeSymbolData(SymbolDataType.AppleDsym, zip.finish()))

        const result = await runHog(['et', 'extract', 'Shop.dSYM'], {
            env: { NO_COLOR: '1' },
            stdoutIsTTY: true,
            cwd: folder,
            useDisk: true,
        })

        expect(result.exitCode).toBe(0)
        expect(result.stdout).not.toContain('\u001b')
        expect(result.stdout).toContain('evil\\x1b]52;c;cGF5\\x07')
    })

    test.each(['<!DOCTYPE plist', ' <?xml version="1.0"', '  <!-- a comment'])(
        'an Info.plist starting with the unterminated markup %p fails to parse',
        async (plist) => {
            const folder = project({ 'Info.plist': plist })

            const result = await runHog(['et', 'release', '--info-plist', 'Info.plist'], {
                env: { ...TEST_CREDENTIALS, CLAUDECODE: '1' },
                cwd: folder,
                useDisk: true,
            })

            expect(result.exitCode).toBe(1)
            expect(result.error()).toMatchObject({ code: 'invalid_info_plist' })
        }
    )

    test.each([
        ['a key without access', ['0192f0a0-0000-7000-8000-000000000001'], 403, 'access_denied'],
        ['a ref lookup with a key without access', ['app.js.map'], 403, 'access_denied'],
        ['an ID PostHog does not have', ['0192f0a0-0000-7000-8000-000000000001'], 404, 'symbol_set_not_found'],
    ])('download fails with a hint for %s', async (_name, args, status, code) => {
        const result = await runHog(['et', 'download', ...args], {
            env: { ...TEST_CREDENTIALS, CLAUDECODE: '1' },
            respond: () => ({ status, body: { detail: 'Not allowed.' } }),
        })

        expect(result.exitCode).toBe(1)
        expect(result.error()).toMatchObject({ code, hint: expect.any(String) })
    })

    test.each([
        ['...dSYM', 'linux', 'symbol_set'],
        ['C:\\build\\symbols.bin', 'win32', 'symbols.bin'],
        ['static/chunks/app.js.map', 'linux', 'app'],
    ] as const)('the base name of %s on %s is %s', (reference, platform, expected) => {
        expect(deriveBaseName(reference, platform)).toBe(expected)
    })
})
