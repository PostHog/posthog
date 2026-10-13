import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, relative } from 'node:path'

import manifest from './terminal-packages.json'
import { TerminalFilesystem } from './terminalFilesystem'
import { TerminalPackage, TerminalPackages } from './terminalPackages'

describe('optional terminal packages', () => {
    const originalGlobals = {
        fetch: globalThis.fetch,
        caches: globalThis.caches,
        Blob: globalThis.Blob,
        Response: globalThis.Response,
        DecompressionStream: globalThis.DecompressionStream,
    }
    const originalAny = Object.getOwnPropertyDescriptor(AbortSignal, 'any')
    const originalSubtle = Object.getOwnPropertyDescriptor(crypto, 'subtle')
    const compressed = new Uint8Array([1, 2, 3])
    const archive = new Uint8Array([4, 5, 6, 7])
    const pkg: TerminalPackage = {
        name: 'Example tool',
        version: '1.0.0',
        file: 'example.tar.gz',
        sha256: createHash('sha256').update(compressed).digest('hex'),
        size: compressed.length,
        archiveSize: archive.length,
        dependencies: [],
        commands: { example: '/opt/posthog-packages/example-1.0.0/bin/example' },
    }
    const response = (): Response => ({ ok: true, arrayBuffer: async () => compressed.slice().buffer }) as Response
    let cached: Response | undefined
    const cache = {
        match: jest.fn(async () => cached),
        put: jest.fn(async (_url: string, value: Response) => {
            cached = value
        }),
        delete: jest.fn(async () => {
            cached = undefined
            return true
        }),
    }
    const mount = (signal = new AbortController().signal, baseUrl?: string): TerminalFilesystem => {
        const filesystem = new TerminalFilesystem()
        new TerminalPackages(
            filesystem,
            signal,
            { example: { ...pkg, baseUrl } },
            'https://raw.githubusercontent.com/example/tools/pinned'
        ).mount()
        return filesystem
    }
    const open = (filesystem: TerminalFilesystem): Promise<{ bytes: Uint8Array }> =>
        filesystem.root.children!.get('packages')!.children!.get('example.tar')!.open!()

    beforeEach(() => {
        cached = undefined
        jest.clearAllMocks()
        Object.defineProperty(AbortSignal, 'any', { configurable: true, value: (signals: AbortSignal[]) => signals[0] })
        Object.defineProperty(crypto, 'subtle', {
            configurable: true,
            value: {
                digest: jest.fn(async (_algorithm: string, data: ArrayBuffer) =>
                    createHash('sha256').update(new Uint8Array(data)).digest()
                ),
            },
        })
        Object.assign(globalThis, {
            fetch: jest.fn(async () => response()),
            caches: { open: jest.fn(async () => cache) },
            Blob: jest.fn(() => ({ stream: () => ({ pipeThrough: () => ({}) }) })),
            Response: jest.fn((bytes?: ArrayBuffer) => ({
                arrayBuffer: async () => (bytes instanceof ArrayBuffer ? bytes : archive.slice().buffer),
                ok: true,
            })),
            DecompressionStream: jest.fn(),
        })
    })

    afterEach(() => {
        Object.assign(globalThis, originalGlobals)
        if (originalAny) {
            Object.defineProperty(AbortSignal, 'any', originalAny)
        } else {
            Reflect.deleteProperty(AbortSignal, 'any')
        }
        if (originalSubtle) {
            Object.defineProperty(crypto, 'subtle', originalSubtle)
        } else {
            Reflect.deleteProperty(crypto, 'subtle')
        }
    })

    it.each(
        Object.entries(manifest.packages).flatMap(([id, pkg]) => Object.keys(pkg.commands).map((cmd) => [id, cmd]))
    )(
        'announces %s command %s after installation, stays quiet on repeat, and allows retry after failure',
        async (id, command) => {
            const directory = mkdtempSync(join(tmpdir(), 'terminal-package-launch-'))
            try {
                const filesystem = new TerminalFilesystem()
                new TerminalPackages(filesystem, new AbortController().signal).mount()
                const bin = filesystem.root.children!.get('bin')!
                const packages: Record<string, TerminalPackage> = manifest.packages
                const pkg = packages[id]
                const installed = join(directory, 'installed')
                const mount = join(directory, 'posthog')
                mkdirSync(join(mount, 'bin'), { recursive: true })
                mkdirSync(join(mount, 'packages'))
                mkdirSync(join(mount, 'config'))
                writeFileSync(join(mount, 'config', 'doom.cfg'), '')
                for (const name of ['install-tool', command]) {
                    const script = new TextDecoder().decode((await bin.children!.get(name)!.open!()).bytes)
                    writeFileSync(
                        join(mount, 'bin', name),
                        script
                            .replaceAll('/opt/posthog-packages', installed)
                            .replaceAll('/posthog/', `${mount}/`)
                            .replaceAll('/tmp/doom', join(directory, 'doom'))
                    )
                }
                for (const dependency of [...pkg.dependencies, id]) {
                    const dependencyPackage = packages[dependency]
                    const stage = join(directory, dependency)
                    for (const entrypoint of new Set(Object.values(dependencyPackage.commands))) {
                        const executable = join(
                            stage,
                            relative(`/opt/posthog-packages/${dependency}-${dependencyPackage.version}`, entrypoint)
                        )
                        mkdirSync(dirname(executable), { recursive: true })
                        writeFileSync(executable, '#!/bin/sh\nprintf "launched:%s\\n" "$@"\n', { mode: 0o700 })
                    }
                    expect(
                        spawnSync('tar', ['-cf', join(mount, 'packages', `${dependency}.tar`), '-C', stage, '.']).status
                    ).toBe(0)
                }
                const run = (): ReturnType<typeof spawnSync> =>
                    spawnSync('/bin/sh', [join(mount, 'bin', command), 'two words'], { encoding: 'utf8' })
                const first = run()
                expect(first).toMatchObject({
                    status: 0,
                    stderr: expect.stringContaining(`Starting ${command}...\n`),
                    stdout: expect.stringContaining('launched:two words\n'),
                })
                const repeated = run()
                expect(repeated).toMatchObject({
                    status: 0,
                    stderr: '',
                    stdout: expect.stringContaining('launched:two words\n'),
                })

                rmSync(join(installed, `${id}-${pkg.version}`), { recursive: true })
                const archivePath = join(mount, 'packages', `${id}.tar`)
                const archive = readFileSync(archivePath)
                writeFileSync(archivePath, 'invalid archive')
                const failed = run()
                expect(failed.status).not.toBe(0)
                expect(failed.stderr).not.toContain('Starting ')
                expect(failed.stdout).toBe('')
                writeFileSync(archivePath, archive)
                const retry = run()
                expect(retry).toMatchObject({
                    status: 0,
                    stderr: expect.stringContaining(`Starting ${command}...\n`),
                    stdout: expect.stringContaining('launched:two words\n'),
                })
            } finally {
                rmSync(directory, { recursive: true, force: true })
            }
        }
    )

    it.each([undefined, 'https://raw.githubusercontent.com/example/tools/package-pin'])(
        'downloads lazily and reuses verified downloads with package source %s',
        async (baseUrl) => {
            const filesystem = mount(undefined, baseUrl)
            expect(fetch).not.toHaveBeenCalled()
            const [first, second] = await Promise.all([open(filesystem), open(filesystem)])
            expect(first.bytes).toEqual(archive)
            expect(second.bytes).toEqual(archive)
            expect(fetch).toHaveBeenCalledTimes(1)
            expect(fetch).toHaveBeenCalledWith(
                `${baseUrl ?? 'https://raw.githubusercontent.com/example/tools/pinned'}/example.tar.gz`,
                expect.objectContaining({ credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer' })
            )
            expect((await open(mount(undefined, baseUrl))).bytes).toEqual(archive)
            expect(fetch).toHaveBeenCalledTimes(1)
        }
    )

    it.each(['network', 'checksum', 'size', 'cached checksum'])(
        'allows retry after a %s failure without exposing unverified bytes',
        async (failure) => {
            const filesystem = mount()
            if (failure === 'network') {
                jest.mocked(fetch).mockRejectedValueOnce(new Error('offline'))
            } else {
                const bad = {
                    ok: true,
                    arrayBuffer: async () => new Uint8Array(failure === 'size' ? [1] : [0, 0, 0]).buffer,
                } as Response
                if (failure === 'cached checksum') {
                    cached = bad
                } else {
                    jest.mocked(fetch).mockResolvedValueOnce(bad)
                }
            }
            await expect(open(filesystem)).rejects.toThrow()
            expect(cache.put).not.toHaveBeenCalled()
            expect((await open(filesystem)).bytes).toEqual(archive)
        }
    )

    it('installs when browser storage is unavailable', async () => {
        jest.mocked(caches.open).mockRejectedValue(new Error('Storage disabled'))
        expect((await open(mount())).bytes).toEqual(archive)
    })

    it('does not expose or cache a download after the terminal closes', async () => {
        const controller = new AbortController()
        jest.mocked(fetch).mockImplementationOnce(async () => {
            controller.abort()
            return response()
        })
        await expect(open(mount(controller.signal))).rejects.toThrow()
        expect(cache.put).not.toHaveBeenCalled()
    })
})
