import { actions, kea, listeners, path, reducers } from 'kea'

import type { wizardSyncDebugLogicType } from './wizardSyncDebugLogicType'

export type SyncDebugKind = 'connect' | 'open' | 'poll' | 'event' | 'error' | 'complete' | 'disconnect'

export interface SyncDebugEntry {
    id: number
    at: number
    source: string
    kind: SyncDebugKind
    message: string
    /** For `poll`/`event` kinds: ms since the previous poll/event from the same source. */
    gapMs: number | null
}

export interface SyncDebugSourceInfo {
    source: string
    mode: 'sse' | 'polling' | null
    intervalMs: number | null
    /** Last poll settle / SSE event arrival. */
    lastAt: number | null
    lastGapMs: number | null
    /** Polls settled or SSE events received. */
    ticks: number
    lastKind: SyncDebugKind
    lastMessage: string
}

const MAX_ENTRIES = 200

let nextEntryId = 0
// Gap tracking lives here rather than in a reducer so `gapMs` can travel on the action payload and
// the reducers stay pure. Module-level is fine: this is a dev-only diagnostic, not app state.
const lastTickAtBySource = new Map<string, number>()

/**
 * Dev-only in-memory event log for the wizard sync transports (task-run SSE/polling, wizard-session
 * SSE/polling). Fed by `logSyncDebug` below and rendered by `WizardSyncDebugPanel`. Never mounted in
 * production — the helper no-ops there, so this logic holds no state outside development.
 */
export const wizardSyncDebugLogic = kea<wizardSyncDebugLogicType>([
    path(['lib', 'wizard-sync', 'wizardSyncDebugLogic']),
    actions({
        recordSyncEvent: (entry: SyncDebugEntry, mode?: 'sse' | 'polling', intervalMs?: number) => ({
            entry,
            mode,
            intervalMs,
        }),
        clearSyncDebugLog: true,
    }),
    reducers({
        entries: [
            [] as SyncDebugEntry[],
            {
                recordSyncEvent: (state, { entry }) => [entry, ...state].slice(0, MAX_ENTRIES),
                clearSyncDebugLog: () => [],
            },
        ],
        sources: [
            {} as Record<string, SyncDebugSourceInfo>,
            {
                recordSyncEvent: (state, { entry, mode, intervalMs }) => {
                    const previous = state[entry.source]
                    const isTick = entry.kind === 'poll' || entry.kind === 'event'
                    return {
                        ...state,
                        [entry.source]: {
                            source: entry.source,
                            mode: mode ?? previous?.mode ?? null,
                            intervalMs: intervalMs ?? previous?.intervalMs ?? null,
                            lastAt: isTick ? entry.at : (previous?.lastAt ?? null),
                            lastGapMs: isTick ? entry.gapMs : (previous?.lastGapMs ?? null),
                            ticks: (previous?.ticks ?? 0) + (isTick ? 1 : 0),
                            lastKind: entry.kind,
                            lastMessage: entry.message,
                        },
                    }
                },
                clearSyncDebugLog: () => ({}),
            },
        ],
    }),
    listeners({
        // Reset the module-level gap tracker too, or the first tick after a clear reports a stale gap.
        clearSyncDebugLog: () => {
            lastTickAtBySource.clear()
        },
    }),
])

/**
 * Record a wizard-sync debug event. No-ops outside development and when the debug panel (the only
 * thing that mounts `wizardSyncDebugLogic`) isn't rendered, so instrumented production code paths
 * pay nothing.
 */
export function logSyncDebug(
    source: string,
    kind: SyncDebugKind,
    message: string,
    opts?: { mode?: 'sse' | 'polling'; intervalMs?: number }
): void {
    if (process.env.NODE_ENV !== 'development') {
        return
    }
    const mounted = wizardSyncDebugLogic.findMounted()
    if (!mounted) {
        return
    }
    const at = Date.now()
    let gapMs: number | null = null
    if (kind === 'poll' || kind === 'event') {
        const last = lastTickAtBySource.get(source)
        gapMs = last !== undefined ? at - last : null
        lastTickAtBySource.set(source, at)
    } else if (kind === 'connect') {
        lastTickAtBySource.delete(source)
    }
    mounted.actions.recordSyncEvent(
        { id: nextEntryId++, at, source, kind, message, gapMs },
        opts?.mode,
        opts?.intervalMs
    )
}
