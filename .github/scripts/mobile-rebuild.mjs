import { readFileSync, realpathSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { isDeepStrictEqual } from 'node:util'

const appPath = 'products/mobile/'
const packagingFiles = new Set(['.easignore', '.node-version', '.npmrc', 'pnpm-workspace.yaml'])
const buildConfigFiles = new Set(['app.json', 'package.json', 'pnpm-lock.yaml', 'src/lib/appVariants.json'])

function buildTooling(path) {
    return (
        buildConfigFiles.has(path) ||
        /^(?:app\.config\.|\.pnpmfile\.|patches\/)/.test(path) ||
        (path.startsWith('plugins/') && !/\.test\.[^/]+$/.test(path))
    )
}

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
                    buildTooling(path) ||
                    path === 'eas.json' ||
                    trackedNativeCode(path) ||
                    nativeModule(path) ||
                    /^(?:assets|targets)\//.test(path))
        )
}

function productionProfile(settingsByName) {
    const profiles = new Map()
    let name = 'production'
    while (name) {
        const profile = settingsByName?.[name]
        if (!profile || profiles.has(name)) {
            throw new Error('Could not resolve the production EAS profile.')
        }
        const { extends: parent, ...settings } = profile
        profiles.set(name, settings)
        name = parent
    }
    return profiles
}

export function fingerprintReasons(before, after) {
    const reasons = []
    for (const [platform, label] of [
        ['ios', 'iOS'],
        ['android', 'Android'],
    ]) {
        if (![before[platform], after[platform]].every((hash) => /^[a-f0-9]{40}$/.test(hash))) {
            throw new Error(`Missing production fingerprint for ${label}.`)
        }
        if (before[platform] !== after[platform]) {
            reasons.push(`${label} native fingerprint changed`)
        }
    }
    return reasons
}

export function rebuildReasons(paths, beforeEas, afterEas) {
    const reasons = []
    if (paths.includes('eas.json')) {
        if (
            !isDeepStrictEqual(beforeEas.cli, afterEas.cli) ||
            !isDeepStrictEqual(productionProfile(beforeEas.build), productionProfile(afterEas.build))
        ) {
            reasons.push('Production EAS build profile changed')
        }
        if (!isDeepStrictEqual(productionProfile(beforeEas.submit), productionProfile(afterEas.submit))) {
            reasons.push('Production EAS submission profile changed')
        }
    }
    if (paths.some(buildTooling)) {
        reasons.push('Mobile build configuration or dependencies changed')
    }
    if (paths.some((path) => packagingFiles.has(path))) {
        reasons.push('Production build packaging or toolchain changed')
    }
    // Expo ignores generated native project directories in the release fingerprint.
    if (paths.some((path) => trackedNativeCode(path) || nativeModule(path))) {
        reasons.push('Tracked native project files changed')
    }
    if (paths.some((path) => path.startsWith('targets/'))) {
        reasons.push('iOS extension target files changed')
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

function readJson(path) {
    return JSON.parse(readFileSync(path, 'utf8'))
}

if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href) {
    const [action, ...files] = process.argv.slice(2)
    if (action === 'scope') {
        const [pathsFile, baseEas, headEas] = files
        const paths = nativeInputs(readFileSync(pathsFile, 'utf8').split('\0'))
        const reasons = rebuildReasons(paths, readJson(baseEas), readJson(headEas))
        console.log(`reason=${reasons.join('. ')}`)
        console.log(`assets=${reasons.length === 0 && paths.some((path) => path.startsWith('assets/'))}`)
    } else if (action === 'fingerprints') {
        console.log(fingerprintReasons(readJson(files[0]), readJson(files[1])).join('. '))
    } else {
        throw new Error(`Unknown mobile rebuild action ${action}`)
    }
}
