import { describe, expect, test } from 'bun:test'
import { readdirSync } from 'node:fs'
import { chmod, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { z } from 'zod'

import { readJson } from '../src/testing'
import type { Artifact } from '../src/updates/manifest'
import { archiveName, TARGETS } from '../src/updates/targets'
import { buildManifest, sha256Sums, wrapperPackageJson } from './artifacts'

const launcher = createRequire(import.meta.url)('./npm/hog.cjs') as {
    targetId: (platform: string, arch: string, musl: boolean) => string | undefined
    isMusl: (readdir: (folder: string) => string[]) => boolean
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

    test.each([
        ['Alpine', { '/lib': ['ld-musl-x86_64.so.1', 'libc.musl-x86_64.so.1'] }, true],
        ['Debian', { '/lib': ['x86_64-linux-gnu'], '/usr/lib': ['os-release'] }, false],
    ])('detects musl on %s', (_name, folders: Record<string, string[]>, musl) => {
        const readdir = (folder: string): string[] => {
            const names = folders[folder]
            if (!names) {
                throw new Error('ENOENT')
            }
            return names
        }
        expect(launcher.isMusl(readdir)).toBe(musl)
    })
})

const here = launcher.targetId(
    process.platform,
    process.arch,
    process.platform === 'linux' && launcher.isMusl(readdirSync)
)
const INSTALL_SH = join(import.meta.dir, 'install.sh')

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

// A release laid out as the workflow publishes it, with a stand-in hog that prints its version.
async function fakeRelease(
    version: string,
    where: 'bucket' | 'mirror',
    options: { checksum?: string; target?: string } = {}
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
    await writeFile(join(build, 'hog'), `#!/bin/sh\necho ${version}\n`)
    await chmod(join(build, 'hog'), 0o755)

    const versionFolder =
        where === 'bucket' ? join(release.bucket, `v${version}`) : join(release.mirror, 'hog', `v${version}`)
    await mkdir(versionFolder, { recursive: true })
    const file = archiveName(target)
    await sh(['tar', '-czf', join(versionFolder, file), '-C', build, 'hog'], root)

    const hasher = new Bun.CryptoHasher('sha256')
    hasher.update(await readFile(join(versionFolder, file)))
    const artifacts: Record<string, Artifact> = {
        [target.id]: { file, sha256: options.checksum ?? hasher.digest('hex'), size: 0 },
    }
    await writeFile(join(versionFolder, 'SHA256SUMS'), sha256Sums(artifacts))

    await mkdir(join(release.bucket, 'stable'), { recursive: true })
    await writeFile(
        join(release.bucket, 'stable', 'manifest.json'),
        JSON.stringify(buildManifest(version, artifacts, { publishedAt: new Date(0), buildDate: new Date(0) }), null, 2)
    )
    await mkdir(release.home, { recursive: true })
    return release
}

// `uname` stands in for the system's, so a test can pretend to run in Git Bash or WSL.
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

// PowerShell reads install.sh as one block comment up to the closing marker, then runs what follows.
// A second marker anywhere above would hand sh code to PowerShell, and `irm | iex` would print parse errors.
test('install.sh closes its PowerShell comment exactly once, after the sh code', async () => {
    const lines = (await Bun.file(INSTALL_SH).text()).split('\n')

    const markers = lines.flatMap((line, index) => (line.includes('#>') ? [index] : []))

    expect(markers).toHaveLength(1)
    expect(lines[markers[0]!]).toBe('#>')
    expect(lines.slice(0, markers[0]).some((line) => line === 'exit')).toBe(true)
})

// npm, pnpm and bun name the global command after the `bin` key, and npx and bunx run the package's
// only bin, so `hog` has to be the one bin in the tarball npm builds, and it has to start with a shebang.
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
