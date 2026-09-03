import { BreakPointFunction, LogicWrapper, MakeLogicType, afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

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
     * tick. Return `unknown` for "cannot tell" (e.g. no access) - the gate fails
     * open. Throwing counts as a detection failure: the gate fails open if nothing
     * has answered yet, and a later blip never downgrades an existing answer.
     */
    detect: () => Promise<ProductSetupStatus>
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
    detectStatusFailure: (error: string, errorObject?: unknown) => { error: string }
    setDetectedStatus: (status: ProductSetupStatus) => { status: ProductSetupStatus }
}

export type SetupDetectionLogicType = MakeLogicType<SetupDetectionValues, SetupDetectionActions>

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
function hasDataCacheKey(teamId: number, productKey: ProductKey): string {
    return `ph-product-setup-has-data/${teamId}/${productKey}`
}

// localStorage can throw (private modes, disabled storage); a cache miss is always safe.
function readCachedHasData(teamId: number | null, productKey: ProductKey): boolean {
    try {
        return teamId !== null && window.localStorage.getItem(hasDataCacheKey(teamId, productKey)) === '1'
    } catch {
        return false
    }
}

function writeCachedHasData(teamId: number | null, productKey: ProductKey): void {
    try {
        if (teamId !== null) {
            window.localStorage.setItem(hasDataCacheKey(teamId, productKey), '1')
        }
    } catch {
        // Nothing cached; the next mount just detects again.
    }
}

export function createSetupDetectionLogic(options: SetupDetectionLogicOptions): LogicWrapper<SetupDetectionLogicType> {
    const { productKey, detect, pollIntervalMs, onDetected, recheckActionTypes, cacheHasData } = options
    return buildKea<SetupDetectionLogicType>([
        path(options.path),
        connect(() => ({
            actions: [productSetupStatusLogic({ productKey }), ['setDetectedStatus']],
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
                detectStatus: async (_: void, breakpoint: BreakPointFunction): Promise<ProductSetupStatus> => {
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
                        if (values.currentProjectId) {
                            actions.detectStatus()
                        }
                    },
                ])
            ),
            detectStatusSuccess: ({ detectedStatus }) => {
                if (!detectedStatus) {
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
            detectStatusFailure: () => {
                // Never strand the gate on its spinner: if nothing (preload included)
                // has answered yet, fail open to the real scene. The poll keeps
                // retrying, and a failure never downgrades an existing answer.
                if (values.setupStatus === 'loading') {
                    actions.setDetectedStatus('unknown')
                }
            },
            [projectLogic.actionTypes.loadCurrentProjectSuccess]: () => {
                // Covers non-polling products mounted before bootstrap settled.
                if (values.detectedStatus === null && !values.detectedStatusLoading) {
                    actions.detectStatus()
                }
            },
        })),
        afterMount(({ actions, values, cache }) => {
            if (cacheHasData && readCachedHasData(values.currentTeamId, productKey)) {
                actions.setDetectedStatus('has-data')
                // The cache skips detection, not the side effects - returning users take
                // this path on every later visit.
                onDetected?.('has-data')
                return
            }
            // The API layer resolves the project from bootstrap state, so a check fired
            // before that settles throws instead of answering - skip those ticks.
            const detectIfProjectKnown = (): void => {
                if (values.currentProjectId) {
                    actions.detectStatus()
                }
            }
            detectIfProjectKnown()
            if (pollIntervalMs) {
                cache.disposables.add(() => {
                    const id = window.setInterval(detectIfProjectKnown, pollIntervalMs)
                    return () => clearInterval(id)
                }, 'poll')
            }
        }),
    ])
}
