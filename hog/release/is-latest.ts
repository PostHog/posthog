// Prints whether this version may move latest, given the manifest latest names now, so a rerun of an older
// release never moves it back. A manifest that can't be read or names no semver version fails the check,
// because the workflow then can't prove this version is the newest. No zod: the publishing job runs this
// without installing hog's dependencies.

import { parseArgs } from 'node:util'

import { compareVersions, parseVersion, type Version } from '../src/updates/version'

async function manifestVersion(path: string): Promise<Version | undefined> {
    try {
        const manifest: unknown = await Bun.file(path).json()
        const version = typeof manifest === 'object' && manifest !== null ? Reflect.get(manifest, 'version') : undefined
        return typeof version === 'string' ? parseVersion(version) : undefined
    } catch {
        return undefined
    }
}

const { values } = parseArgs({ options: { version: { type: 'string' }, current: { type: 'string' } } })
const version = values.version && parseVersion(values.version)
if (!version || !values.current) {
    console.error('Pass the release version with --version, and the manifest latest names now with --current.')
    process.exit(1)
}

const current = await manifestVersion(values.current)
if (!current) {
    console.error(`${values.current} isn't a release manifest with a semver version.`)
    process.exit(1)
}

process.stdout.write(`${String(compareVersions(version, current) >= 0)}\n`)
