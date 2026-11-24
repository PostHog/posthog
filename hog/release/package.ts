// --reuse rebuilds the npm packages and formula from a version the bucket already has, because files
// under a version never change.

import { chmod, copyFile, cp, mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { parseArgs } from 'node:util'

import type { Artifact, Manifest } from '../src/updates/manifest'
import { archiveName, npmPackageName, shippedBinaries, TARGETS, type Target } from '../src/updates/targets'
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
import { HOG_ROOT, RELEASE_FOLDER, run, targetFolder } from './shared'

const { values } = parseArgs({
    options: {
        in: { type: 'string', default: RELEASE_FOLDER },
        out: { type: 'string', default: join(RELEASE_FOLDER, 'out') },
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

async function sha256(path: string): Promise<string> {
    const hasher = new Bun.CryptoHasher('sha256')
    hasher.update(await readFile(path))
    return hasher.digest('hex')
}

function binaryPath(target: Target, name: string): string {
    return join(targetFolder(input, target), name)
}

async function archive(target: Target): Promise<Artifact> {
    const folder = targetFolder(input, target)
    const file = archiveName(target)
    const destination = join(assets, file)
    const names = shippedBinaries(target)
    for (const name of names) {
        await chmod(binaryPath(target, name), 0o755)
    }

    // Both files at the root of the archive, so install.sh, install.ps1, Homebrew and `hog upgrade`
    // all find `hog` and `hog-worker` there and place them in one folder.
    if (target.os === 'win32') {
        await run(['zip', '-j', '-X', '-q', destination, ...names.map((name) => binaryPath(target, name))], folder)
    } else {
        // Keeps macOS tar from adding a `._` entry for each file's extended attributes.
        await run(['tar', '-czf', destination, '-C', folder, ...names], folder, { COPYFILE_DISABLE: '1' })
    }

    return { file, sha256: await sha256(destination), size: (await stat(destination)).size }
}

async function writeJson(path: string, value: unknown): Promise<void> {
    await writeFile(path, JSON.stringify(value, null, 2) + '\n')
}

// The page npm shows for the hog package. Platform packages only point to it.
const NPM_README = join(HOG_ROOT, 'release/npm/README.md')

const PLATFORM_README = (name: string): string =>
    `# ${name}\n\nThe hog binary for one platform. Install \`hog\` instead: \`npm install -g hog\`.\n\n` +
    'See https://www.npmjs.com/package/hog.\n'

async function npmPackage(
    folder: string,
    packageJson: PackageJson,
    files: [string, string][],
    readme: string
): Promise<void> {
    await mkdir(join(folder, 'bin'), { recursive: true })
    await writeJson(join(folder, 'package.json'), packageJson)
    await writeFile(join(folder, 'README.md'), readme)
    for (const [from, to] of files) {
        await copyFile(from, join(folder, to))
        await chmod(join(folder, to), 0o755)
    }
}

async function reuse(from: string, manifest: Manifest): Promise<Record<string, Artifact>> {
    await cp(from, assets, { recursive: true })
    for (const target of TARGETS) {
        const artifact = manifest.artifacts[target.id]
        if (!artifact || (await sha256(join(assets, artifact.file))) !== artifact.sha256) {
            throw new Error(`${from} has no ${target.id} archive that matches its manifest.`)
        }
        const folder = targetFolder(input, target)
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
        // The folder holds what the archive ships and nothing else: the workflow signs every file in it,
        // and the installers install every file in the archive.
        const built = await readdir(targetFolder(input, target)).catch(() => [])
        if (built.sort().join() !== shippedBinaries(target).sort().join()) {
            throw new Error(
                `${targetFolder(input, target)} holds [${built.join(', ')}], and a release ships [${shippedBinaries(target).join(', ')}]. Run release/compile.ts and release/build-worker.sh for every target first.`
            )
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
        shippedBinaries(target).map((name) => [binaryPath(target, name), join('bin', name)]),
        PLATFORM_README(npmPackageName(target))
    )
}
await npmPackage(
    join(out, 'npm', 'hog'),
    wrapperPackageJson(version),
    [[join(HOG_ROOT, 'release/npm/hog.cjs'), 'bin/hog.cjs']],
    await readFile(NPM_README, 'utf8')
)

await writeFile(join(out, 'hog.rb'), homebrewFormula(version, artifacts))

console.info(`Packaged hog ${version} into ${out}`)
