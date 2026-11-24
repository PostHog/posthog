import { describe, expect, test } from 'bun:test'
import { readdirSync } from 'node:fs'
import { chmod, mkdir, mkdtemp, readFile, stat, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { z } from 'zod'

import { readJson } from '../src/testing'
import type { Artifact } from '../src/updates/manifest'
import { archiveName, rustTarget, shippedBinaries, TARGETS } from '../src/updates/targets'
import { buildManifest, sha256Sums, wrapperPackageJson } from './artifacts'

const launcher = createRequire(import.meta.url)('./npm/hog.cjs') as {
    targetId: (platform: string, arch: string, musl: boolean) => string | undefined
    libcFamily: (ldd: string | undefined, report: unknown) => string | undefined
    candidates: (platform: string, arch: string, libc: string | undefined) => string[]
}

describe('npm launcher', () => {
    test.each(TARGETS.map((target) => [target.id, target]))('picks %s on its own platform', (id, target) => {
        expect(launcher.targetId(target.os, target.cpu, target.libc === 'musl')).toBe(id)
    })

    test.each([
        ['freebsd', 'x64'],
        ['linux', 'ia32'],
    ])('has no build for %s on %s', (platform, arch) => {
        expect(launcher.targetId(platform, arch, false)).toBeUndefined()
    })

    const GLIBC_LDD =
        '#!/bin/bash\necho "ldd (GNU libc) 2.39"\n# Copyright (C) 2024 Free Software Foundation, Inc.\n# GNU C Library\n'
    const MUSL_LDD = '#!/bin/sh\nexec /lib/ld-musl-x86_64.so.1 --list "$@"\n'

    test.each([
        ['glibc, even with musl installed', GLIBC_LDD, { sharedObjects: ['/lib/ld-musl-x86_64.so.1'] }, 'glibc'],
        ['Alpine', MUSL_LDD, {}, 'musl'],
        [
            'an ldd npm does not recognize, whatever the report says',
            '#!/bin/sh\n',
            { header: { glibcVersionRuntime: '2.39' } },
            undefined,
        ],
        ['glibc without ldd', undefined, { header: { glibcVersionRuntime: '2.39' } }, 'glibc'],
        ['musl without ldd', undefined, { header: {}, sharedObjects: ['/lib/ld-musl-x86_64.so.1'] }, 'musl'],
        ['an unknown libc', undefined, { header: {} }, undefined],
    ])('reads the libc of %s as npm does', (_name, ldd, report, libc) => {
        expect(launcher.libcFamily(ldd, report)).toBe(libc)
    })

    test('falls back to the other libc build on Linux only', () => {
        expect(launcher.candidates('linux', 'x64', 'glibc')).toEqual(['linux-x64', 'linux-x64-musl'])
        expect(launcher.candidates('linux', 'arm64', 'musl')).toEqual(['linux-arm64-musl', 'linux-arm64'])
        expect(launcher.candidates('darwin', 'arm64', undefined)).toEqual(['darwin-arm64'])
    })
})

// A new target gets its triple checked here before release/build-worker.ts builds a worker for it.
test('every target builds hog-worker for its own Rust triple', () => {
    expect(Object.fromEntries(TARGETS.map((target) => [target.id, rustTarget(target)]))).toEqual({
        'darwin-arm64': 'aarch64-apple-darwin',
        'darwin-x64': 'x86_64-apple-darwin',
        'linux-x64': 'x86_64-unknown-linux-gnu',
        'linux-arm64': 'aarch64-unknown-linux-gnu',
        'linux-x64-musl': 'x86_64-unknown-linux-musl',
        'linux-arm64-musl': 'aarch64-unknown-linux-musl',
        'windows-x64': 'x86_64-pc-windows-msvc',
        'windows-arm64': 'aarch64-pc-windows-msvc',
    })
})

const IS_LATEST = join(import.meta.dir, 'is-latest.ts')

// The publishing job promotes only on "true", so anything it can't compare must fail instead of answering.
describe('is-latest', () => {
    test.each([
        ['an older latest', '{"version":"0.1.0-alpha.2"}', 0, 'true'],
        ['the same version', '{"version":"0.1.0-alpha.3"}', 0, 'true'],
        ['a newer latest', '{"version":"0.2.0"}', 0, 'false'],
        ['a manifest with no version', '{}', 1, ''],
        ['a version that is not semver', '{"version":"latest"}', 1, ''],
        ['a file that is not JSON', '<Error><Code>AccessDenied</Code></Error>', 1, ''],
    ])('answers for %s', async (_name, manifest, exitCode, stdout) => {
        const path = join(await mkdtemp(join(tmpdir(), 'hog-latest-')), 'manifest.json')
        await writeFile(path, manifest)

        const child = Bun.spawnSync([process.execPath, IS_LATEST, '--version', '0.1.0-alpha.3', '--current', path])

        expect(child.exitCode).toBe(exitCode)
        expect(child.stdout.toString().trim()).toBe(stdout)
    })
})

const hostHasMuslLoader = ['/lib', '/usr/lib'].some((folder) => {
    try {
        return readdirSync(folder).some((name) => name.startsWith('ld-musl-'))
    } catch {
        return false
    }
})
const here = launcher.targetId(process.platform, process.arch, process.platform === 'linux' && hostHasMuslLoader)
const INSTALL_SH = join(import.meta.dir, 'install.sh')

const MUSL_MISSING_LIBRARY = 'Error loading shared library libstdc++.so.6: No such file or directory (needed by hog)'
const EXIT_LOADER_FAILED = 127

interface FakeRelease {
    root: string
    bucket: string
    mirror: string
    home: string
    installDir: string
}

async function sh(command: string[], cwd: string): Promise<void> {
    const child = Bun.spawn(command, { cwd, stdout: 'ignore', stderr: 'inherit' })
    expect(await child.exited).toBe(0)
}

async function fakeRelease(
    version: string,
    where: 'bucket' | 'mirror',
    options: {
        checksum?: string
        target?: string
        broken?: 'hog' | 'hog-worker' | 'hog without libstdc++'
        worker?: boolean
    } = {}
): Promise<FakeRelease> {
    const root = await mkdtemp(join(tmpdir(), 'hog-install-'))
    const release: FakeRelease = {
        root,
        bucket: join(root, 'bucket'),
        mirror: join(root, 'mirror'),
        home: join(root, 'home'),
        installDir: join(root, 'home', 'bin'),
    }
    const target = TARGETS.find((candidate) => candidate.id === (options.target ?? here))!

    const build = join(root, 'build')
    await mkdir(build, { recursive: true })
    const files = options.worker === false ? ['hog'] : ['hog', 'hog-worker']
    for (const name of files) {
        // Like hog, the stand-in starts the worker next to it when the installer asks for the check.
        const check =
            files.length > 1 ? '[ -z "$HOG_CHECK_INSTALL" ] || "$(dirname "$0")/hog-worker" >/dev/null || exit 1\n' : ''
        let script = name === 'hog' ? `${check}echo ${version}` : `echo worker ${version}`
        if (options.broken === name) {
            script = 'exit 1'
        } else if (name === 'hog' && options.broken === 'hog without libstdc++') {
            script = `echo '${MUSL_MISSING_LIBRARY}' >&2\nexit ${EXIT_LOADER_FAILED}`
        }
        await writeFile(join(build, name), `#!/bin/sh\n${script}\n`)
        await chmod(join(build, name), 0o755)
    }

    const versionFolder =
        where === 'bucket' ? join(release.bucket, `v${version}`) : join(release.mirror, 'hog', `v${version}`)
    await mkdir(versionFolder, { recursive: true })
    const file = archiveName(target)
    await sh(['tar', '-czf', join(versionFolder, file), '-C', build, ...files], root)

    const hasher = new Bun.CryptoHasher('sha256')
    hasher.update(await readFile(join(versionFolder, file)))
    const artifacts: Record<string, Artifact> = {
        [target.id]: { file, sha256: options.checksum ?? hasher.digest('hex'), size: 0 },
    }
    await writeFile(join(versionFolder, 'SHA256SUMS'), sha256Sums(artifacts))

    await mkdir(join(release.bucket, 'latest'), { recursive: true })
    await writeFile(
        join(release.bucket, 'latest', 'manifest.json'),
        JSON.stringify(buildManifest(version, artifacts, { publishedAt: new Date(0), buildDate: new Date(0) }), null, 2)
    )
    await mkdir(release.home, { recursive: true })
    return release
}

async function install(
    release: FakeRelease,
    args: string[] = [],
    uname?: { s: string; m: string }
): Promise<{ exitCode: number; stdout: string; stderr: string }> {
    let path = process.env.PATH ?? ''
    if (uname) {
        const bin = join(release.root, 'fake-bin')
        await mkdir(bin, { recursive: true })
        await writeFile(
            join(bin, 'uname'),
            `#!/bin/sh\ncase "$1" in -m) echo ${uname.m} ;; *) echo ${uname.s} ;; esac\n`
        )
        await chmod(join(bin, 'uname'), 0o755)
        path = `${bin}:${path}`
    }
    const child = Bun.spawn(['sh', INSTALL_SH, ...args], {
        env: {
            PATH: path,
            HOME: release.home,
            SHELL: '/bin/zsh',
            HOG_RELEASES_URL: `file://${release.bucket}`,
            HOG_MIRROR_URL: `file://${release.mirror}`,
            HOG_INSTALL_DIR: release.installDir,
        },
        stdout: 'pipe',
        stderr: 'pipe',
    })
    const [stdout, stderr, exitCode] = await Promise.all([
        new Response(child.stdout).text(),
        new Response(child.stderr).text(),
        child.exited,
    ])
    return { exitCode, stdout, stderr }
}

function receiptPath(release: FakeRelease): string {
    return process.platform === 'darwin'
        ? join(release.home, 'Library', 'Application Support', 'hog', 'install.json')
        : join(release.home, '.config', 'hog', 'install.json')
}

describe.skipIf(process.platform === 'win32' || !here)('install.sh', () => {
    test('installs the latest release and records the install', async () => {
        const release = await fakeRelease('0.1.0-alpha.3', 'bucket')

        const result = await install(release)

        expect(result.stderr).toBe('')
        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain(`Installed hog 0.1.0-alpha.3 to ${release.installDir}/hog.`)
        expect(result.stdout).toContain(`export PATH="${release.installDir}:$PATH"`)
        expect(await readFile(join(release.installDir, 'hog-worker'), 'utf8')).toContain('echo worker 0.1.0-alpha.3')
        expect((await stat(join(release.installDir, 'hog-worker'))).mode & 0o111).toBe(0o111)
        expect(await Bun.file(receiptPath(release)).json()).toEqual({
            method: 'script',
            install_dir: release.installDir,
            version: '0.1.0-alpha.3',
            target: here,
        })
    })

    test('falls back to the GitHub mirror for a pinned version the bucket lacks', async () => {
        const release = await fakeRelease('1.2.3', 'mirror')

        const result = await install(release, ['--version', 'v1.2.3'])

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain('Installed hog 1.2.3')
    })

    test('installs nothing when the archive does not match SHA256SUMS', async () => {
        const release = await fakeRelease('1.2.3', 'bucket', { checksum: '0'.repeat(64) })

        const result = await install(release, ['--version', '1.2.3'])

        expect(result.exitCode).toBe(1)
        expect(result.stderr).toContain("doesn't match SHA256SUMS")
        expect(await Bun.file(join(release.installDir, 'hog')).exists()).toBe(false)
    })

    test.each([
        ['hog', "doesn't run on this machine"],
        ['hog-worker', "doesn't run on this machine"],
        ['hog without libstdc++', 'apk add libstdc++ libgcc'],
    ] as const)('keeps the installed pair when the new %s does not run here, and says why', async (broken, reason) => {
        const release = await fakeRelease('1.2.3', 'bucket', { broken })
        await mkdir(release.installDir, { recursive: true })
        await writeFile(join(release.installDir, 'hog'), '#!/bin/sh\necho 1.0.0\n')
        await writeFile(join(release.installDir, 'hog-worker'), '#!/bin/sh\necho worker 1.0.0\n')

        const result = await install(release, ['--version', '1.2.3'])

        expect(result.exitCode).toBe(1)
        expect(result.stderr).toContain(reason)
        expect(await readFile(join(release.installDir, 'hog'), 'utf8')).toBe('#!/bin/sh\necho 1.0.0\n')
        expect(await readFile(join(release.installDir, 'hog-worker'), 'utf8')).toBe('#!/bin/sh\necho worker 1.0.0\n')
        expect(readdirSync(release.installDir).sort()).toEqual(['hog', 'hog-worker'])
    })

    test('keeps the installed hog when a folder sits where the worker goes', async () => {
        const release = await fakeRelease('1.2.3', 'bucket')
        await mkdir(join(release.installDir, 'hog-worker'), { recursive: true })
        await writeFile(join(release.installDir, 'hog'), '#!/bin/sh\necho 1.0.0\n')

        const result = await install(release, ['--version', '1.2.3'])

        expect(result.exitCode).toBe(1)
        expect(result.stderr).toContain('hog-worker is a folder')
        expect(await readFile(join(release.installDir, 'hog'), 'utf8')).toBe('#!/bin/sh\necho 1.0.0\n')
        expect(readdirSync(join(release.installDir, 'hog-worker'))).toEqual([])
    })

    test('installs a release from before hog-worker without one', async () => {
        const release = await fakeRelease('0.1.0', 'bucket', { worker: false })

        const result = await install(release, ['--version', '0.1.0'])

        expect(result.exitCode).toBe(0)
        expect(readdirSync(release.installDir)).toEqual(['hog'])
    })

    test('points Git Bash to the PowerShell installer and installs nothing', async () => {
        const release = await fakeRelease('1.2.3', 'bucket', { target: 'windows-x64' })

        const result = await install(release, [], { s: 'MINGW64_NT-10.0-19045', m: 'x86_64' })

        expect(result.exitCode).toBe(1)
        expect(result.stderr).toContain(
            'powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://releases.posthog.com/hog/install.ps1 | iex"'
        )
        expect(await Bun.file(join(release.installDir, 'hog')).exists()).toBe(false)
    })

    test('installs the Linux build in WSL, which reports Linux', async () => {
        const release = await fakeRelease('1.2.3', 'bucket', { target: 'linux-x64' })

        const result = await install(release, [], { s: 'Linux', m: 'x86_64' })

        expect(result.exitCode).toBe(0)
        expect(result.stdout).toContain('Installing hog 1.2.3 for linux-x64.')
    })
})

// A second closing marker would hand sh code to PowerShell, and `irm install.sh | iex` would print parse errors.
test('install.sh closes its PowerShell comment exactly once, after the sh code', async () => {
    const lines = (await Bun.file(INSTALL_SH).text()).split('\n')

    const markers = lines.flatMap((line, index) => (line.includes('#>') ? [index] : []))

    expect(markers).toHaveLength(1)
    expect(lines[markers[0]!]).toBe('#>')
    expect(lines.slice(0, markers[0]).some((line) => line === 'exit')).toBe(true)
})

// Package managers name the command after the `bin` key, and npx and bunx run a package's only bin.
test.skipIf(!Bun.which('npm'))('the npm launcher package installs the hog command', async () => {
    const folder = await mkdtemp(join(tmpdir(), 'hog-npm-'))
    await mkdir(join(folder, 'bin'))
    await writeFile(join(folder, 'package.json'), JSON.stringify(wrapperPackageJson('0.1.0-alpha.1')))
    await writeFile(join(folder, 'bin', 'hog.cjs'), await readFile(join(import.meta.dir, 'npm', 'hog.cjs')))

    const pack = Bun.spawnSync(['npm', 'pack', '--dry-run', '--json', '--ignore-scripts'], { cwd: folder })

    expect(pack.exitCode).toBe(0)
    const [tarball] = readJson(pack.stdout.toString(), PackOutput)
    expect(tarball!.files.map((file) => file.path).sort()).toEqual(['bin/hog.cjs', 'package.json'])
    expect(wrapperPackageJson('0.1.0-alpha.1').bin).toEqual({ hog: 'bin/hog.cjs' })
    expect((await readFile(join(folder, 'bin', 'hog.cjs'), 'utf8')).startsWith('#!/usr/bin/env node\n')).toBe(true)
})

const PackOutput = z.array(z.object({ files: z.array(z.object({ path: z.string() })) }))

async function listing(command: string[]): Promise<string[]> {
    const child = Bun.spawn(command, { stdout: 'pipe', stderr: 'inherit' })
    const [text, exitCode] = await Promise.all([new Response(child.stdout).text(), child.exited])
    expect(exitCode).toBe(0)
    return text.split('\n').filter(Boolean).sort()
}

// hog starts hog-worker only from its own folder, so a channel that ships one without the other ships a
// hog whose error-tracking commands fail.
test.skipIf(!Bun.which('zip') || !Bun.which('unzip'))(
    'package.ts puts hog-worker next to hog in every archive, npm package and the formula',
    async () => {
        const root = await mkdtemp(join(tmpdir(), 'hog-package-'))
        for (const target of TARGETS) {
            await mkdir(join(root, 'bin', target.id), { recursive: true })
            for (const name of shippedBinaries(target)) {
                await writeFile(join(root, 'bin', target.id, name), `${target.id} ${name}`)
            }
        }
        const out = join(root, 'out')

        await sh(
            [
                'bun',
                join(import.meta.dir, 'package.ts'),
                '--in',
                root,
                '--out',
                out,
                '--version',
                '1.2.3',
                '--build-date',
                '2026-01-01T00:00:00Z',
            ],
            root
        )

        for (const target of TARGETS) {
            const names = shippedBinaries(target).sort()
            const archive = join(out, 'assets', archiveName(target))
            expect(await listing(target.os === 'win32' ? ['unzip', '-Z1', archive] : ['tar', '-tzf', archive])).toEqual(
                names
            )
            expect(readdirSync(join(out, 'npm', `hog-${target.id}`, 'bin')).sort()).toEqual(names)
            const packageJson = readJson(
                await readFile(join(out, 'npm', `hog-${target.id}`, 'package.json'), 'utf8'),
                z.object({ files: z.array(z.string()) })
            )
            expect(packageJson.files.sort()).toEqual(names.map((name) => `bin/${name}`))
        }
        expect(await readFile(join(out, 'hog.rb'), 'utf8')).toContain('bin.install Dir["*"]')
    }
)
