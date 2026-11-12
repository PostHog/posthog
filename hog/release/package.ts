// Packages the binaries compile.ts built into everything a release publishes:
//
//   <out>/assets/    the archives, SHA256SUMS, manifest.json and both install scripts. The release
//                    workflow uploads this folder to releases.posthog.com/hog/v<version>/ and to the
//                    GitHub release, then copies manifest.json to hog/stable/manifest.json.
//   <out>/npm/       one folder per npm package, ready for `npm publish <folder>`
//   <out>/hog.rb     the Homebrew formula for PostHog/homebrew-tap
//
//   bun release/package.ts --version 0.1.0-alpha.4 --build-date <iso> [--in dist/release] [--out dist/release/out]
//   bun release/package.ts --reuse <assets folder> [--out dist/release/out]
//
// Pass the same --version and --build-date as compile.ts. release/minimum-version.json sets the
// manifest's minimumVersion: every hog below it warns on each command, so it retires a broken release.
//
// --reuse takes the assets of a version the bucket already has, as on a rerun, and builds the npm
// packages and the formula from those archives. Files under a version never change, and a new
// signature would give the same version different bytes.

import { chmod, copyFile, cp, mkdir, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { parseArgs } from 'node:util'

import type { Artifact, Manifest } from '../src/updates/manifest'
import { archiveName, binaryName, npmPackageName, TARGETS, type Target } from '../src/updates/targets'
import { parseVersion } from '../src/updates/version'
import {
    buildManifest,
    homebrewFormula,
    type PackageJson,
    platformPackageJson,
    sha256Sums,
    wrapperPackageJson,
} from './artifacts'
import minimum from './minimum-version.json' with { type: 'json' }

const HOG_ROOT = resolve(import.meta.dir, '..')

const { values } = parseArgs({
    options: {
        in: { type: 'string', default: join(HOG_ROOT, 'dist/release') },
        out: { type: 'string', default: join(HOG_ROOT, 'dist/release/out') },
        version: { type: 'string' },
        'build-date': { type: 'string' },
        reuse: { type: 'string' },
    },
})

const reused = values.reuse ? ((await Bun.file(join(values.reuse, 'manifest.json')).json()) as Manifest) : undefined

if (!reused && (!values.version || !values['build-date'] || Number.isNaN(Date.parse(values['build-date'])))) {
    console.error('Pass --version and --build-date, the same ones compile.ts got, or --reuse.')
    process.exit(1)
}

const minimumVersion = minimum.minimumVersion ?? undefined
if (minimumVersion !== undefined && !parseVersion(minimumVersion)) {
    console.error(`release/minimum-version.json names ${minimumVersion}, which isn't a semver version.`)
    process.exit(1)
}

const out = resolve(values.out)
const input = reused ? join(out, 'unpacked') : resolve(values.in)
const version = reused?.version ?? values.version!
const assets = join(out, 'assets')

async function run(command: string[], cwd: string): Promise<void> {
    const child = Bun.spawn(command, { cwd, stdout: 'inherit', stderr: 'inherit' })
    if ((await child.exited) !== 0) {
        throw new Error(`${command.join(' ')} failed`)
    }
}

async function sha256(path: string): Promise<string> {
    const hasher = new Bun.CryptoHasher('sha256')
    hasher.update(await readFile(path))
    return hasher.digest('hex')
}

function binaryPath(target: Target): string {
    return join(input, 'bin', target.id, binaryName(target))
}

async function archive(target: Target): Promise<Artifact> {
    const folder = join(input, 'bin', target.id)
    const file = archiveName(target)
    const destination = join(assets, file)
    await chmod(binaryPath(target), 0o755)

    // One file at the root of the archive, so install.sh, install.ps1 and Homebrew all find `hog` there.
    if (target.os === 'win32') {
        await run(['zip', '-j', '-X', '-q', destination, binaryPath(target)], folder)
    } else {
        await run(['tar', '-czf', destination, '-C', folder, binaryName(target)], folder)
    }

    return { file, sha256: await sha256(destination), size: (await stat(destination)).size }
}

async function writeJson(path: string, value: unknown): Promise<void> {
    await writeFile(path, JSON.stringify(value, null, 2) + '\n')
}

const NPM_README = (name: string): string =>
    `# ${name}\n\nhog, the PostHog command line. Install it with \`npm install -g @posthog/hog\`.\n\n` +
    'See https://github.com/PostHog/posthog/tree/master/hog for the commands.\n'

async function npmPackage(folder: string, packageJson: PackageJson, files: [string, string][]): Promise<void> {
    await mkdir(join(folder, 'bin'), { recursive: true })
    await writeJson(join(folder, 'package.json'), packageJson)
    await writeFile(join(folder, 'README.md'), NPM_README(packageJson.name))
    for (const [from, to] of files) {
        await copyFile(from, join(folder, to))
        await chmod(join(folder, to), 0o755)
    }
}

// The published assets as they are, with each binary unpacked for its npm package.
async function reuse(from: string, manifest: Manifest): Promise<Record<string, Artifact>> {
    await cp(from, assets, { recursive: true })
    for (const target of TARGETS) {
        const artifact = manifest.artifacts[target.id]
        if (!artifact || (await sha256(join(assets, artifact.file))) !== artifact.sha256) {
            throw new Error(`${from} has no ${target.id} archive that matches its manifest.`)
        }
        const folder = join(input, 'bin', target.id)
        await mkdir(folder, { recursive: true })
        const archivePath = join(assets, artifact.file)
        await run(
            target.os === 'win32'
                ? ['unzip', '-o', '-q', archivePath, '-d', folder]
                : ['tar', '-xzf', archivePath, '-C', folder],
            folder
        )
    }
    return manifest.artifacts
}

await rm(out, { recursive: true, force: true })
await mkdir(assets, { recursive: true })

let artifacts: Record<string, Artifact> = {}
if (reused) {
    artifacts = await reuse(resolve(values.reuse!), reused)
} else {
    for (const target of TARGETS) {
        if (!(await Bun.file(binaryPath(target)).exists())) {
            throw new Error(`Missing ${binaryPath(target)}. Run release/compile.ts for every target first.`)
        }
        artifacts[target.id] = await archive(target)
        console.info(`Packaged ${artifacts[target.id]!.file}`)
    }

    await writeFile(join(assets, 'SHA256SUMS'), sha256Sums(artifacts))
    const dates = { publishedAt: new Date(), buildDate: new Date(values['build-date']!) }
    await writeJson(join(assets, 'manifest.json'), buildManifest(version, artifacts, dates, minimumVersion))
    await copyFile(join(HOG_ROOT, 'release/install.sh'), join(assets, 'install.sh'))
    await copyFile(join(HOG_ROOT, 'release/install.ps1'), join(assets, 'install.ps1'))
}

for (const target of TARGETS) {
    await npmPackage(
        join(out, 'npm', npmPackageName(target).replace('@posthog/', '')),
        platformPackageJson(target, version),
        [[binaryPath(target), join('bin', binaryName(target))]]
    )
}
await npmPackage(join(out, 'npm', 'hog'), wrapperPackageJson(version), [
    [join(HOG_ROOT, 'release/npm/hog.cjs'), 'bin/hog.cjs'],
])

await writeFile(join(out, 'hog.rb'), homebrewFormula(version, artifacts))

console.info(`Packaged hog ${version} into ${out}`)
