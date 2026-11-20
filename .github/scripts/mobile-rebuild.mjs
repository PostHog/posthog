import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { isDeepStrictEqual } from 'node:util'

const appPath = 'products/mobile/'
const packagingFiles = new Set(['.easignore', '.node-version', '.npmrc', 'pnpm-workspace.yaml'])
const fingerprintFiles = new Set([
    'app.config.ts',
    'eas.json',
    'package.json',
    'pnpm-lock.yaml',
    'src/lib/appVariants.json',
])

function trackedNativeCode(path) {
    return path.startsWith('ios/') || (path.startsWith('android/') && !/\/src\/(?:test|androidTest)\//.test(path))
}

function nativeModule(path) {
    const moduleFile = /^modules\/[^/]+\/(.+)$/.exec(path)?.[1]
    return (
        moduleFile &&
        (moduleFile === 'expo-module.config.json' || moduleFile === 'package.json' || trackedNativeCode(moduleFile))
    )
}

export function nativeInputs(paths) {
    return paths
        .filter((path) => path.startsWith(appPath))
        .map((path) => path.slice(appPath.length))
        .filter(
            (path) =>
                !path.endsWith('.md') &&
                (packagingFiles.has(path) ||
                    fingerprintFiles.has(path) ||
                    trackedNativeCode(path) ||
                    nativeModule(path) ||
                    /^(?:assets|patches|targets)\//.test(path) ||
                    (/^plugins\//.test(path) && !/\.test\.[^/]+$/.test(path)))
        )
}

function productionProfile({ build, cli }) {
    const profiles = new Map()
    let name = 'production'
    while (name) {
        const profile = build?.[name]
        if (!profile || profiles.has(name)) {
            throw new Error('Could not resolve the production EAS profile.')
        }
        const { extends: parent, ...settings } = profile
        profiles.set(name, settings)
        name = parent
    }
    return { cli, profiles }
}

export function rebuildReasons(paths, before, after) {
    const reasons = []
    for (const [platform, label] of [
        ['ios', 'iOS'],
        ['android', 'Android'],
    ]) {
        if (![before.hashes[platform], after.hashes[platform]].every((hash) => /^[a-f0-9]{40}$/.test(hash))) {
            throw new Error(`Missing production fingerprint for ${label}.`)
        }
        if (before.hashes[platform] !== after.hashes[platform]) {
            reasons.push(`${label} native fingerprint changed`)
        }
    }
    if (!isDeepStrictEqual(productionProfile(before.eas), productionProfile(after.eas))) {
        reasons.push('Production EAS build profile changed')
    }
    if (paths.some((path) => packagingFiles.has(path))) {
        reasons.push('Production build packaging or toolchain changed')
    }
    // Expo ignores generated native project directories in the release fingerprint.
    if (paths.some(trackedNativeCode)) {
        reasons.push('Tracked native project files changed')
    }
    return reasons
}

export function rebuildCommand(sha) {
    if (!/^[a-f0-9]{40}$/.test(sha)) {
        throw new Error('Expected a full pull request head SHA.')
    }
    return `/ack-mobile-rebuild ${sha}`
}

export async function findAcknowledgement(comments, sha, canWrite) {
    const command = rebuildCommand(sha)
    for await (const { body, user } of comments) {
        if (user?.type === 'User' && body?.trim() === command && (await canWrite(user.login))) {
            return user.login
        }
    }
    return null
}

function loadSnapshot(directory, hashFile) {
    return {
        eas: JSON.parse(readFileSync(`${directory}/eas.json`, 'utf8')),
        hashes: JSON.parse(readFileSync(hashFile, 'utf8')),
    }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    const [action, pathsFile, baseDir, headDir, baseHashFile, headHashFile] = process.argv.slice(2)
    const paths = nativeInputs(readFileSync(pathsFile, 'utf8').split('\0'))
    if (action === 'scope') {
        console.log(paths.length > 0)
    } else if (action === 'compare') {
        const reasons = rebuildReasons(paths, loadSnapshot(baseDir, baseHashFile), loadSnapshot(headDir, headHashFile))
        console.log(reasons.join('. '))
    } else {
        throw new Error(`Unknown mobile rebuild action ${action}`)
    }
}
