import { BreakPointFunction, LogicWrapper, MakeLogicType, afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import { isScopeNotFoundError } from 'lib/api-error'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { productSetupStatusLogic } from './productSetupStatusLogic'
import type { ProductSetupStatus } from './types'

// Alias kea so kea-typegen skips this factory - the logic type is hand-written below.
const buildKea = kea

export interface SetupDetectionLogicOptions {
    productKey: ProductKey
    /** kea path, e.g. `['products', 'logs', 'frontend', 'emptyState', 'logsSetupLogic']` */
    path: string[]
    /**
     * Resolve the product's current setup status. Runs on mount and on every poll
     * tick. Return `unknown` to show the scene (e.g. its access-denied screen).
     * Return `null` when the check cannot answer. Like throwing, this fails the
     * gate open if nothing has answered yet and preserves an existing answer.
     */
    detect: () => Promise<ProductSetupStatus | null>
    /**
     * Re-check cadence while the product has no data yet, so the empty state flips
     * to the real scene on its own once events land. Polling stops for good on the
     * first `has-data` answer, and pauses on hidden tabs. Omit for products whose
     * status only changes through in-app actions (entity counts) - the gate
     * remounts this logic on every scene entry, which is fresh enough.
     */
    pollIntervalMs?: number
    /** Side effects on each successful detection (product intents, setup-task completion). */
    onDetected?: (status: ProductSetupStatus) => void
    /**
     * Action types (e.g. `teamLogic.actionTypes.updateCurrentTeamSuccess`) that
     * trigger an immediate re-detect, for products whose status hangs off state
     * changed elsewhere in the app - a team-setting opt-in, an entity created
     * from a modal. Without one, the next poll tick (or scene re-entry) is the
     * only refresh. A function, because `actionTypes` cannot be read at module
     * import time - it is evaluated when this logic mounts.
     */
    recheckActionTypes?: () => string[]
    /**
     * Remember a has-data answer in localStorage (keyed team + product) and skip
     * detection on later mounts. Only that direction is cached - data never
     * disappears once ingested, while needs-setup keeps re-checking. For products
     * without a boot-time probe, this is what spares the returning user a spinner
     * and a query on every scene entry.
     */
    cacheHasData?: boolean
    /**
     * With `cacheHasData`, still run detection once in the background after a cached
     * has-data answer opens the gate. For products whose data users can delete (entity
     * counts: dashboards, cohorts, notebooks) or that age out of the probe's window
     * (retention, lookbacks). The gate never waits for this check. A `needs-setup` or
     * `waiting-for-data` answer replaces the cached status and clears the cache, so
     * the empty state shows again. A failure, `null` or `unknown` keeps has-data.
     */
    revalidateCachedHasData?: boolean
}

export interface SetupDetectionValues {
    detectedStatus: ProductSetupStatus | null
    detectedStatusLoading: boolean
    setupStatus: ProductSetupStatus
    currentProjectId: number | null
    currentTeamId: number | null
}

export interface SetupDetectionActions {
    detectStatus: () => void
    detectStatusSuccess: (
        detectedStatus: ProductSetupStatus | null,
        payload?: void
    ) => { detectedStatus: ProductSetupStatus | null }
    detectStatusFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    setDetectedStatus: (status: ProductSetupStatus) => { status: ProductSetupStatus }
    applyDetectedStatus: (
        status: ProductSetupStatus,
        teamId: number | null
    ) => { status: ProductSetupStatus; teamId: number | null }
}

export type SetupDetectionLogicType = MakeLogicType<SetupDetectionValues, SetupDetectionActions>

const HAS_DATA_CACHE_PREFIX = 'ph-product-setup-has-data/'

function hasDataCacheKey(teamId: number, productKey: ProductKey): string {
    return `${HAS_DATA_CACHE_PREFIX}${teamId}/${productKey}`
}

/** Drops every product's cached has-data answer, so isolated renders (stories) detect afresh. */
export function clearAllCachedHasData(): void {
    try {
        Object.keys(window.localStorage)
            .filter((key) => key.startsWith(HAS_DATA_CACHE_PREFIX))
            .forEach((key) => window.localStorage.removeItem(key))
    } catch {
        // Storage is unavailable, so nothing was cached either.
    }
}

// localStorage can throw (private modes, disabled storage); every read/write miss is
// safe, since the caller either re-detects or just skips caching the answer.
function withHasDataCacheKey<T>(
    teamId: number | null,
    productKey: ProductKey,
    fallback: T,
    run: (key: string) => T
): T {
    try {
        return teamId === null ? fallback : run(hasDataCacheKey(teamId, productKey))
    } catch {
        return fallback
    }
}

function readCachedHasData(teamId: number | null, productKey: ProductKey): boolean {
    return withHasDataCacheKey(teamId, productKey, false, (key) => window.localStorage.getItem(key) === '1')
}

function writeCachedHasData(teamId: number | null, productKey: ProductKey): void {
    withHasDataCacheKey(teamId, productKey, undefined, (key) => window.localStorage.setItem(key, '1'))
}

function clearCachedHasData(teamId: number | null, productKey: ProductKey): void {
    withHasDataCacheKey(teamId, productKey, undefined, (key) => window.localStorage.removeItem(key))
}

/**
 * Builds a product's empty-state detection logic: the piece that answers "is this
 * product set up?" and pushes the answer into `productSetupStatusLogic`. Wraps the
 * contract every adoption re-implemented by hand - detect on mount, poll until data
 * arrives, fail open on errors - so a product only supplies its `detect` function:
 *
 * ```ts
 * export const logsSetupLogic = createSetupDetectionLogic({
 *     productKey: ProductKey.LOGS,
 *     path: ['products', 'logs', 'frontend', 'emptyState', 'logsSetupLogic'],
 *     detect: async () => ((await api.logs.hasLogs()) ? 'has-data' : 'needs-setup'),
 *     pollIntervalMs: 20000,
 * })
 * ```
 *
 * Products whose detection drives more than the gate (extra selectors, multi-stage
 * dashboards like MCP analytics) keep a bespoke logic instead.
 */
export function createSetupDetectionLogic(options: SetupDetectionLogicOptions): LogicWrapper<SetupDetectionLogicType> {
    const {
        productKey,
        detect,
        pollIntervalMs,
        onDetected,
        recheckActionTypes,
        cacheHasData,
        revalidateCachedHasData,
    } = options
    return buildKea<SetupDetectionLogicType>([
        path(options.path),
        connect(() => ({
            actions: [productSetupStatusLogic({ productKey }), ['setDetectedStatus', 'applyDetectedStatus']],
            values: [
                productSetupStatusLogic({ productKey }),
                ['status as setupStatus'],
                projectLogic,
                ['currentProjectId'],
                teamLogic,
                ['currentTeamId'],
            ],
        })),
        loaders({
            detectedStatus: {
                __default: null as ProductSetupStatus | null,
                detectStatus: async (_: void, breakpoint: BreakPointFunction): Promise<ProductSetupStatus | null> => {
                    const status = await detect()
                    breakpoint()
                    return status
                },
            },
        }),
        listeners(({ actions, values, cache }) => ({
            ...Object.fromEntries(
                (recheckActionTypes?.() ?? []).map((actionType) => [
                    actionType,
                    () => {
                        // Rechecks exist to flip the gate open after the first entity is created
                        // in place; once it is open, another probe changes nothing.
                        if (values.currentProjectId && values.setupStatus !== 'has-data') {
                            actions.detectStatus()
                        }
                    },
                ])
            ),
            detectStatusSuccess: ({ detectedStatus }) => {
                const revalidating = cache.cacheGate === 'armed'
                if (revalidating) {
                    cache.cacheGate = 'closed'
                    // The cached has-data already opened the gate and ran onDetected. Only a
                    // definite "no data" answer changes anything, and it must bypass the
                    // guard that stops needs-setup replacing has-data.
                    if (detectedStatus === 'needs-setup' || detectedStatus === 'waiting-for-data') {
                        clearCachedHasData(values.currentTeamId, productKey)
                        actions.applyDetectedStatus(detectedStatus, values.currentTeamId)
                        onDetected?.(detectedStatus)
                        startPoll(cache, actions, values, pollIntervalMs)
                    }
                    return
                }
                if (!detectedStatus) {
                    if (values.setupStatus === 'loading') {
                        actions.setDetectedStatus('unknown')
                    }
                    return
                }
                actions.setDetectedStatus(detectedStatus)
                onDetected?.(detectedStatus)
                // Data never disappears once it exists, so the poll's job is done.
                if (detectedStatus === 'has-data') {
                    cache.disposables.dispose('poll')
                    if (cacheHasData) {
                        writeCachedHasData(values.currentTeamId, productKey)
                    }
                }
            },
            detectStatusFailure: ({ errorObject }) => {
                if (cache.cacheGate === 'armed') {
                    cache.cacheGate = 'closed'
                }
                // Never strand the gate on its spinner: if nothing (preload included)
                // has answered yet, fail open to the real scene. The poll keeps
                // retrying, and a failure never downgrades an existing answer.
                if (values.setupStatus === 'loading') {
                    actions.setDetectedStatus('unknown')
                }
                // A deleted project (or one the user lost access to) 404s every request
                // under it, so retrying only files one error per tick. Stop the poll and
                // leave the scene routing to move the user off the dead URL.
                if (isScopeNotFoundError(errorObject)) {
                    cache.disposables.dispose('poll')
                }
            },
            [projectLogic.actionTypes.loadCurrentProjectSuccess]: () => {
                // Covers non-polling products mounted before bootstrap settled. A cache hit
                // gates this off, except for one still-armed revalidation catch-up. The action
                // can fire with the project still null, so detectIfProjectKnown re-checks it.
                if (cache.cacheGate !== 'closed' && values.detectedStatus === null && !values.detectedStatusLoading) {
                    detectIfProjectKnown(actions, values)
                }
            },
        })),
        afterMount(({ actions, values, cache }) => {
            if (cacheHasData && readCachedHasData(values.currentTeamId, productKey)) {
                actions.setDetectedStatus('has-data')
                // The cache skips detection, not the side effects - returning users take
                // this path on every later visit.
                onDetected?.('has-data')
                cache.cacheGate = revalidateCachedHasData ? 'armed' : 'closed'
                if (revalidateCachedHasData) {
                    // Before bootstrap settles, the loadCurrentProjectSuccess listener runs it.
                    detectIfProjectKnown(actions, values)
                }
                return
            }
            detectIfProjectKnown(actions, values)
            startPoll(cache, actions, values, pollIntervalMs)
        }),
    ])
}

// The API layer resolves the project from bootstrap state, so a check fired before
// that settles throws instead of answering - skip those ticks.
function detectIfProjectKnown(
    actions: Pick<SetupDetectionLogicType['actions'], 'detectStatus'>,
    values: Pick<SetupDetectionValues, 'currentProjectId'>
): void {
    if (values.currentProjectId) {
        actions.detectStatus()
    }
}

function startPoll(
    cache: Record<string, any>,
    actions: Pick<SetupDetectionLogicType['actions'], 'detectStatus'>,
    values: Pick<SetupDetectionValues, 'currentProjectId'>,
    pollIntervalMs: number | undefined
): void {
    if (pollIntervalMs) {
        cache.disposables.add(() => {
            const id = window.setInterval(() => detectIfProjectKnown(actions, values), pollIntervalMs)
            return () => clearInterval(id)
        }, 'poll')
    }
}
