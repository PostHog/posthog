import { MakeLogicType, BreakPointFunction, actions, afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import {
    ApiError,
    isBrowserNetworkFailure,
    isScopeNotFoundError,
    isUnavailableEndpointError,
    NetworkError,
    readableErrorMessage,
} from 'lib/api-error'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { productSetupStatusLogic } from './productSetupStatusLogic'
import type { ProductSetupStatus } from './types'

export interface SetupDetectionProps {
    productKey: ProductKey
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
     * Read a status straight from a recheck action's payload, so a reload that already
     * answers skips the probe. Return `null` to probe. Do not combine with
     * `allowReturnToSetup`: that path applies a probe's answer directly, so a late
     * no-data probe answer could replace has-data.
     */
    statusFromRecheck?: (payload: Record<string, any>) => ProductSetupStatus | null
    /**
     * Remember a has-data answer in localStorage (keyed team + product) and skip
     * detection on later mounts. Only that direction is cached - data never
     * disappears once ingested, while needs-setup keeps re-checking. For products
     * without a boot-time probe, this is what spares the returning user a spinner
     * and a query on every scene entry. A function decides per has-data answer, for a
     * product whose has-data can come from data that goes away.
     */
    cacheHasData?: boolean | (() => boolean)
    /** Entity products can become empty when users delete their last item. Recheck mutations even after data exists. */
    allowReturnToSetup?: boolean
    /**
     * With `cacheHasData`, re-run detection once in the background after a cached has-data
     * answer, for data users can delete or that ages out of the probe's window. A no-data answer
     * clears the cache so the next visit shows the empty state. It never replaces the mounted scene.
     */
    revalidateCachedHasData?: boolean
}

const HAS_DATA_CACHE_PREFIX = 'ph-product-setup-has-data/'

function hasDataCacheKey(teamId: number, productKey: ProductKey): string {
    return `${HAS_DATA_CACHE_PREFIX}${teamId}/${productKey}`
}

// localStorage throws in private modes or when disabled; a miss only costs a re-detect.
function tryStorage<T>(fallback: T, run: (storage: Storage) => T): T {
    try {
        return run(window.localStorage)
    } catch {
        return fallback
    }
}

/** Drops every product's cached has-data answer, so isolated renders (stories, tests) detect afresh. */
export function clearAllCachedHasData(): void {
    tryStorage(undefined, (storage) =>
        Object.keys(storage)
            .filter((key) => key.startsWith(HAS_DATA_CACHE_PREFIX))
            .forEach((key) => storage.removeItem(key))
    )
}

function readCachedHasData(teamId: number | null, productKey: ProductKey): boolean {
    return (
        teamId !== null && tryStorage(false, (storage) => storage.getItem(hasDataCacheKey(teamId, productKey)) === '1')
    )
}

function writeCachedHasData(teamId: number | null, productKey: ProductKey): void {
    if (teamId !== null) {
        tryStorage(undefined, (storage) => storage.setItem(hasDataCacheKey(teamId, productKey), '1'))
    }
}

function clearCachedHasData(teamId: number | null, productKey: ProductKey): void {
    if (teamId !== null) {
        tryStorage(undefined, (storage) => storage.removeItem(hasDataCacheKey(teamId, productKey)))
    }
}

function isNoDataStatus(status: ProductSetupStatus | null): status is 'needs-setup' | 'waiting-for-data' {
    return status === 'needs-setup' || status === 'waiting-for-data'
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface setupDetectionLogicValues {
    setupStatus: ProductSetupStatus // productSetupStatusLogic
    currentProjectId: number | null // projectLogic
    currentTeamId: number | null // teamLogic
    detectedStatus: ProductSetupStatus | null
    detectedStatusLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface setupDetectionLogicActions {
    setDetectedStatus: (status: ProductSetupStatus) => {
        status: ProductSetupStatus
    } // productSetupStatusLogic
    detectStatus: (_: void) => void
    detectStatusFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    detectStatusSuccess: (
        detectedStatus: ProductSetupStatus | null,
        payload?: void
    ) => {
        detectedStatus: ProductSetupStatus | null
        payload?: void
    }
    revalidateCachedStatus: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface setupDetectionLogicMeta {
    key: any
}

export type setupDetectionLogicType = MakeLogicType<
    setupDetectionLogicValues,
    setupDetectionLogicActions,
    SetupDetectionProps,
    setupDetectionLogicMeta
>

/**
 * Answers "is this product set up?" for a product's empty-state gate, and pushes the
 * answer into `productSetupStatusLogic`. It holds the contract every adoption
 * re-implemented by hand - detect on mount, poll until data arrives, fail open on
 * errors - so a product only supplies its settings, keyed by its product key:
 *
 * ```ts
 * export const logsSetupDetection: SetupDetectionProps = {
 *     productKey: ProductKey.LOGS,
 *     detect: async () => ((await api.logs.hasLogs()) ? 'has-data' : 'needs-setup'),
 *     pollIntervalMs: 20000,
 * }
 * // the gate mounts setupDetectionLogic(logsSetupDetection)
 * ```
 *
 * Products whose detection drives more than the gate (extra selectors, multi-stage
 * dashboards like MCP analytics) keep a bespoke logic instead.
 */
export const setupDetectionLogic = kea<setupDetectionLogicType>([
    props({} as SetupDetectionProps),
    key((props) => props.productKey),
    path((key) => ['lib', 'components', 'ProductEmptyState', 'setupDetectionLogic', key]),
    connect((props: SetupDetectionProps) => ({
        actions: [productSetupStatusLogic({ productKey: props.productKey }), ['setDetectedStatus']],
        values: [
            productSetupStatusLogic({ productKey: props.productKey }),
            ['status as setupStatus'],
            projectLogic,
            ['currentProjectId'],
            teamLogic,
            ['currentTeamId'],
        ],
    })),
    actions({ revalidateCachedStatus: true }),
    loaders(({ cache, props }) => ({
        detectedStatus: {
            __default: null as ProductSetupStatus | null,
            detectStatus: async (_: void, breakpoint: BreakPointFunction): Promise<ProductSetupStatus | null> => {
                const status = await detectOrNullOnOutageOrForbidden(props.detect, () =>
                    cache.disposables.dispose('poll')
                )
                breakpoint()
                return status
            },
        },
    })),
    listeners(({ actions, values, cache, props }) => ({
        ...Object.fromEntries(
            (props.recheckActionTypes?.() ?? []).map((actionType) => [
                actionType,
                (payload: Record<string, any>) => {
                    if (values.currentProjectId && (props.allowReturnToSetup || values.setupStatus !== 'has-data')) {
                        const status = props.statusFromRecheck?.(payload)
                        if (status) {
                            actions.detectStatusSuccess(status)
                        } else {
                            actions.detectStatus()
                        }
                    }
                },
            ])
        ),
        revalidateCachedStatus: async () => {
            const teamId = values.currentTeamId
            const status = await detectOrNull(props.detect)
            if (isNoDataStatus(status)) {
                clearCachedHasData(teamId, props.productKey)
            }
        },
        detectStatusSuccess: ({ detectedStatus }) => {
            if (!detectedStatus) {
                if (values.setupStatus === 'loading') {
                    actions.setDetectedStatus('unknown')
                }
                return
            }
            if (props.allowReturnToSetup && isNoDataStatus(detectedStatus)) {
                clearCachedHasData(values.currentTeamId, props.productKey)
                productSetupStatusLogic({ productKey: props.productKey }).actions.applyDetectedStatus(
                    detectedStatus,
                    values.currentTeamId
                )
            } else {
                actions.setDetectedStatus(detectedStatus)
            }
            props.onDetected?.(detectedStatus)
            // Data never disappears once it exists, so the poll's job is done.
            if (detectedStatus === 'has-data') {
                cache.disposables.dispose('poll')
                if (typeof props.cacheHasData === 'function' ? props.cacheHasData() : props.cacheHasData) {
                    writeCachedHasData(values.currentTeamId, props.productKey)
                }
            }
        },
        detectStatusFailure: ({ errorObject }) => {
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
            const run = cache.runWhenProjectKnown
            if (run && values.currentProjectId) {
                cache.runWhenProjectKnown = null
                run()
            }
        },
    })),
    afterMount(({ actions, values, cache, props }) => {
        if (props.cacheHasData && readCachedHasData(values.currentTeamId, props.productKey)) {
            actions.setDetectedStatus('has-data')
            // The cache skips detection, not the side effects - returning users take
            // this path on every later visit.
            props.onDetected?.('has-data')
            if (props.revalidateCachedHasData) {
                runOnceProjectIsKnown(cache, values, actions.revalidateCachedStatus)
            }
            return
        }
        runOnceProjectIsKnown(cache, values, actions.detectStatus)
        startPoll(cache, actions, values, props.pollIntervalMs)
    }),
])

async function detectOrNull(detect: () => Promise<ProductSetupStatus | null>): Promise<ProductSetupStatus | null> {
    try {
        return await detect()
    } catch {
        return null
    }
}

// A 5xx, a dropped connection or a 403 says nothing about setup, and the gate treats null as
// "cannot answer". Throwing would file one error tracking issue per product for each failure.
// A 403 does not clear on retry, so it also stops the poll.
async function detectOrNullOnOutageOrForbidden(
    detect: () => Promise<ProductSetupStatus | null>,
    onForbidden: () => void
): Promise<ProductSetupStatus | null> {
    try {
        return await detect()
    } catch (error) {
        if (error instanceof ApiError && error.status === 403) {
            onForbidden()
            return null
        }
        if (error instanceof NetworkError || isBrowserNetworkFailure(error) || isUnanswerableProbeResponse(error)) {
            return null
        }
        throw error
    }
}

// A 404 or 405 for an endpoint is what a deploy in progress looks like, when the new frontend
// reaches a backend pod that does not serve the probe route yet. A 4xx without a readable body
// did not come from our API code (a proxy in front of it sent it), so it is not a probe bug either.
// A dead-scope 404 is excluded, because `detectStatusFailure` must stop the poll for it, and a 4xx
// that carries a detail is excluded, so a real probe bug such as a bad parameter stays visible.
function isUnanswerableProbeResponse(error: unknown): boolean {
    if (!(error instanceof ApiError) || error.status === undefined) {
        return false
    }
    if (error.status >= 500) {
        return true
    }
    if (error.status < 400 || isScopeNotFoundError(error)) {
        return false
    }
    return isUnavailableEndpointError(error) || readableErrorMessage(error.data) === undefined
}

function runOnceProjectIsKnown(
    cache: Record<string, any>,
    values: Pick<setupDetectionLogicType['values'], 'currentProjectId'>,
    run: () => void
): void {
    if (values.currentProjectId) {
        run()
    } else {
        cache.runWhenProjectKnown = run
    }
}

function startPoll(
    cache: Record<string, any>,
    actions: Pick<setupDetectionLogicType['actions'], 'detectStatus'>,
    values: Pick<setupDetectionLogicType['values'], 'currentProjectId'>,
    pollIntervalMs: number | undefined
): void {
    if (pollIntervalMs) {
        cache.disposables.add(() => {
            const id = window.setInterval(() => {
                if (values.currentProjectId) {
                    actions.detectStatus()
                }
            }, pollIntervalMs)
            return () => clearInterval(id)
        }, 'poll')
    }
}
