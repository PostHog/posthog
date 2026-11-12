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

const CACHE_FILE = 'update-check.json'
const DAY_MS = 24 * 60 * 60 * 1000
const SETUP_MAX_AGE_MS = 10 * 60 * 1000
// The daily check runs alongside the command, so a slow answer costs at most this much at the end.
const BACKGROUND_TIMEOUT_MS = 1500
const SETUP_TIMEOUT_MS = 5000
const RETRY_AFTER_FAILURE_MS = 60 * 60 * 1000

export const NO_UPDATE_CHECK_ENV = ['HOG_NO_UPDATE_CHECK'] as const

const LatestSchema = z.object({
    version: z.string(),
    publishedAt: z.string(),
    minimumVersion: z.string().optional(),
})

const CacheSchema = z.object({
    checkedAt: z.number(),
    latest: LatestSchema.optional(),
    failedAt: z.number().optional(),
})

type Latest = z.infer<typeof LatestSchema>
type Cache = z.infer<typeof CacheSchema>

// A run from source and a local `pnpm compile` have no build date, so they never check.
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

async function saveCache(runtime: Runtime, cache: Cache): Promise<void> {
    await runtime.writePrivateFile(hogFile(runtime, CACHE_FILE), `${JSON.stringify(cache)}\n`).catch(() => {})
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
    await saveCache(runtime, cache)
    return cache
}

// An outage never slows every command: the daily check falls back to the cache and backs off for an hour.
async function latestRelease(
    runtime: Runtime,
    options: { maxAgeMs: number; timeoutMs: number; setup: boolean }
): Promise<Latest | undefined> {
    const cache = await readCache(runtime)
    if (cache?.latest && runtime.now() - cache.checkedAt < options.maxAgeMs) {
        return cache.latest
    }
    if (!options.setup && cache?.failedAt !== undefined && runtime.now() - cache.failedAt < RETRY_AFTER_FAILURE_MS) {
        return cache.latest
    }
    try {
        return (await writeCache(runtime, await fetchManifest(runtime, { timeoutMs: options.timeoutMs }))).latest
    } catch {
        if (options.setup) {
            return undefined
        }
        await saveCache(runtime, { checkedAt: cache?.checkedAt ?? 0, latest: cache?.latest, failedAt: runtime.now() })
        return cache?.latest
    }
}

const DAILY = { maxAgeMs: DAY_MS, timeoutMs: BACKGROUND_TIMEOUT_MS, setup: false }

export async function rememberRelease(runtime: Runtime, manifest: Manifest): Promise<void> {
    await writeCache(runtime, manifest)
}

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

// Off stops every update request, minimumVersion included. Only the setup gate still checks.
export function updateChecksOff(
    runtime: Pick<Runtime, 'env'>,
    config: { cli?: { updateCheck?: boolean } } | undefined
): boolean {
    return optOutFlag(runtime.env, NO_UPDATE_CHECK_ENV) === true || config?.cli?.updateCheck === false
}

export async function currentVersionInfo(runtime: Runtime, off: boolean): Promise<HogVersionInfo> {
    if (!checksUpdates(runtime)) {
        return versionInfo(runtime, undefined)
    }
    const latest = off ? (await readCache(runtime))?.latest : await latestRelease(runtime, DAILY)
    return versionInfo(runtime, latest)
}

// Any newer release stops setup, even one patch. An unreachable or untrusted manifest doesn't.
export async function requireLatestForSetup(runtime: Runtime, rerun: string, tlsOff: boolean): Promise<HogVersionInfo> {
    if (!checksUpdates(runtime) || tlsOff) {
        return versionInfo(runtime, undefined)
    }

    const latest = await latestRelease(runtime, {
        maxAgeMs: SETUP_MAX_AGE_MS,
        timeoutMs: SETUP_TIMEOUT_MS,
        setup: true,
    })
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

export class UpdateCheck {
    private readonly pending: Promise<Latest | undefined>

    constructor(
        private readonly runtime: Runtime,
        off: boolean
    ) {
        this.pending =
            checksUpdates(runtime) && !off
                ? latestRelease(runtime, DAILY).catch(() => undefined)
                : Promise.resolve(undefined)
    }

    // A release below minimumVersion warns everyone. The notice is only for a person at a terminal.
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
