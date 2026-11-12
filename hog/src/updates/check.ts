import { z } from 'zod'

import type { Mode } from '@/core/agent'
import { isRunningInCI } from '@/core/ci'
import { HogError } from '@/core/errors'
import { optOutFlag } from '@/core/globals'
import { parseJsonOrUndefined } from '@/core/json'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'

import { detectInstallMethod, upgradeAdvice, upgradeCommand, type InstallMethod } from './install-method'
import { fetchManifest, type Manifest } from './manifest'
import { isMeaningfullyBehind, isNewer } from './version'

// The latest release as hog last read it, kept in hog's folder so most runs need no request.
const CACHE_FILE = 'update-check.json'
const DAY_MS = 24 * 60 * 60 * 1000
// Setup wants the latest version, so it accepts only a recent answer.
const SETUP_MAX_AGE_MS = 10 * 60 * 1000
// The daily check runs alongside the command, so a slow answer costs at most this much at the end.
const BACKGROUND_TIMEOUT_MS = 1500
const SETUP_TIMEOUT_MS = 5000

export const NO_UPDATE_CHECK_ENV = ['HOG_NO_UPDATE_CHECK'] as const

const LatestSchema = z.object({
    version: z.string(),
    publishedAt: z.string(),
    minimumVersion: z.string().optional(),
})

const CacheSchema = z.object({ checkedAt: z.number(), latest: LatestSchema })

type Latest = z.infer<typeof LatestSchema>
type Cache = z.infer<typeof CacheSchema>

// Only a release build knows when it was built. A run from source and a local `pnpm compile` have no
// build date, so they never check.
export function checksUpdates(runtime: Pick<Runtime, 'isDevelopment' | 'build'>): boolean {
    return !runtime.isDevelopment && runtime.build.date !== undefined
}

async function readCache(runtime: Runtime): Promise<Cache | undefined> {
    try {
        return parseJsonOrUndefined(await runtime.readFile(hogFile(runtime, CACHE_FILE)), CacheSchema)
    } catch {
        return undefined
    }
}

async function writeCache(runtime: Runtime, manifest: Manifest): Promise<Cache> {
    const cache: Cache = {
        checkedAt: runtime.now(),
        latest: {
            version: manifest.version,
            publishedAt: manifest.publishedAt,
            ...(manifest.minimumVersion ? { minimumVersion: manifest.minimumVersion } : {}),
        },
    }
    await runtime.writePrivateFile(hogFile(runtime, CACHE_FILE), `${JSON.stringify(cache)}\n`).catch(() => {})
    return cache
}

// The cached answer when it is younger than `maxAgeMs`, or a fresh one. A failed request falls back
// to the cache, however old, and to undefined without one: an unreachable release never fails a command.
export async function latestRelease(
    runtime: Runtime,
    maxAgeMs: number,
    timeoutMs: number
): Promise<Latest | undefined> {
    const cache = await readCache(runtime)
    if (cache && runtime.now() - cache.checkedAt < maxAgeMs) {
        return cache.latest
    }
    try {
        return (await writeCache(runtime, await fetchManifest(runtime, { timeoutMs }))).latest
    } catch {
        return cache?.latest
    }
}

export async function rememberRelease(runtime: Runtime, manifest: Manifest): Promise<void> {
    await writeCache(runtime, manifest)
}

// What `hog auth status` and `hog setup` tell agents about the running hog.
export interface HogVersionInfo {
    version: string
    latest: string | null
    updateAvailable: boolean
    command: string | null
}

async function versionInfo(
    runtime: Runtime,
    latest: Latest | undefined,
    method?: InstallMethod
): Promise<HogVersionInfo> {
    const updateAvailable = latest !== undefined && isNewer(latest.version, runtime.build.version)
    const command = updateAvailable ? upgradeCommand(method ?? (await detectInstallMethod(runtime))) : undefined
    return {
        version: runtime.build.version,
        latest: latest?.version ?? null,
        updateAvailable,
        command: command ?? null,
    }
}

// HOG_NO_UPDATE_CHECK and `cli.updateCheck: false` stop every update request, the minimumVersion
// check included. Only the setup gate still checks, because setup needs the latest version.
export function updateChecksOff(
    runtime: Pick<Runtime, 'env'>,
    config: { cli?: { updateCheck?: boolean } } | undefined
): boolean {
    return optOutFlag(runtime.env, NO_UPDATE_CHECK_ENV) === true || config?.cli?.updateCheck === false
}

// With update checks off it reads only what an earlier check cached, and sends no request.
export async function currentVersionInfo(runtime: Runtime, off: boolean): Promise<HogVersionInfo> {
    if (!checksUpdates(runtime)) {
        return versionInfo(runtime, undefined)
    }
    const latest = off
        ? (await readCache(runtime))?.latest
        : await latestRelease(runtime, DAY_MS, BACKGROUND_TIMEOUT_MS)
    return versionInfo(runtime, latest)
}

// Setup has the best chance with the latest hog, so it stops on any newer release, even one patch.
// It doesn't stop when the release can't be read, or for a dev build.
export async function requireLatestForSetup(runtime: Runtime, rerun: string): Promise<HogVersionInfo> {
    if (!checksUpdates(runtime)) {
        return versionInfo(runtime, undefined)
    }

    const latest = await latestRelease(runtime, SETUP_MAX_AGE_MS, SETUP_TIMEOUT_MS)
    const method = await detectInstallMethod(runtime)
    const info = await versionInfo(runtime, latest, method)
    if (info.updateAvailable) {
        throw new HogError(
            'hog_outdated',
            `Setup needs the latest hog, ${info.latest}, and this is ${info.version}.`,
            upgradeAdvice(method, rerun),
            undefined,
            { version: info.version, latest: info.latest, command: info.command ?? upgradeCommand(method) ?? null }
        )
    }
    return info
}

// Started when a command starts and finished when it ends, so the request overlaps the command.
export class UpdateCheck {
    private readonly pending: Promise<Latest | undefined>

    // `off` is updateChecksOff: then hog sends no request and prints nothing.
    constructor(
        private readonly runtime: Runtime,
        off: boolean
    ) {
        this.pending =
            checksUpdates(runtime) && !off
                ? latestRelease(runtime, DAY_MS, BACKGROUND_TIMEOUT_MS).catch(() => undefined)
                : Promise.resolve(undefined)
    }

    // Lines for stderr once the command printed its output. A release below the manifest's minimum
    // warns everyone, agents and CI included. The notice is only for a person at a terminal who is
    // meaningfully behind.
    async finish(options: { mode: Mode; command: string | undefined }): Promise<void> {
        const latest = await this.pending
        if (!latest || options.command === 'upgrade') {
            return
        }
        const { runtime } = this
        const current = runtime.build.version

        if (latest.minimumVersion && isNewer(latest.minimumVersion, current)) {
            const method = await detectInstallMethod(runtime)
            const command = upgradeCommand(method)
            const message = `hog ${current} has a known problem. Update to ${latest.version}.`
            const hint = command ? `Run \`${command}\`.` : upgradeAdvice(method, '<command>')
            runtime.writeStderr(
                options.mode.format === 'json'
                    ? `${JSON.stringify({ warning: { code: 'hog_below_minimum_version', message, hint, latest: latest.version, command: command ?? null } })}\n`
                    : `Warning: ${message} ${hint}\n`
            )
            return
        }

        const person = options.mode.format === 'text' && options.mode.agent === undefined && runtime.stdoutIsTTY
        const buildDate = runtime.build.date
        if (
            !person ||
            isRunningInCI(runtime.env) ||
            !buildDate ||
            !isMeaningfullyBehind({ version: current, buildDate }, latest)
        ) {
            return
        }

        const method = await detectInstallMethod(runtime)
        const command = upgradeCommand(method)
        if (!command || method.kind === 'npx') {
            return
        }
        runtime.writeStderr(`hog ${latest.version} is out (you have ${current}). Run \`${command}\` to update.\n`)
    }
}
