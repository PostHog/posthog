import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import type { sessionRecordingInfoLogicType } from './sessionRecordingInfoLogicType'

export enum RecordingExistsState {
    Loading = 'loading',
    Exists = 'exists',
    NotExists = 'not_exists',
    Error = 'error',
}

export type RecordingExistsStorage = Record<string, RecordingExistsState>

export interface SummaryOutcome {
    description?: string | null
}

// 'error' is distinct from null so a transient fetch failure stays retryable
// instead of being cached as "no outcome".
export type StoredOutcome = SummaryOutcome | null | 'error'

export interface PendingFetch {
    wantsExistence: boolean
    wantsOutcome: boolean
}

export function selectOutcome<T extends { description?: string | null }>(
    candidates: ReadonlyArray<T | null | undefined>
): T | null {
    for (const candidate of candidates) {
        if (candidate?.description) {
            return candidate
        }
    }
    return null
}

const BATCH_SIZE = 100

export const sessionRecordingInfoLogic = kea<sessionRecordingInfoLogicType>([
    path(['lib', 'components', 'ViewRecordingButton', 'sessionRecordingInfoLogic']),
    actions({
        checkRecordingInfo: (sessionId: string, options?: { includeOutcome?: boolean }) => ({
            sessionId,
            includeOutcome: !!options?.includeOutcome,
        }),
        enqueuePending: (sessionId: string, want: keyof PendingFetch) => ({ sessionId, want }),
        removePending: (sessionIds: string[]) => ({ sessionIds }),
        recordExistence: (updates: RecordingExistsStorage) => ({ updates }),
        recordOutcomes: (outcomes: Record<string, StoredOutcome>) => ({ outcomes }),
        flushPending: true,
    }),
    reducers({
        // Choosing not to persist here as we cache on the BE; client memory shouldn't grow forever.
        recordingExistsStorage: [
            {} as RecordingExistsStorage,
            {
                recordExistence: (state, { updates }) => ({ ...state, ...updates }),
            },
        ],
        outcomeBySessionId: [
            {} as Record<string, StoredOutcome>,
            {
                recordOutcomes: (state, { outcomes }) => ({ ...state, ...outcomes }),
            },
        ],
        pendingFetches: [
            {} as Record<string, PendingFetch>,
            {
                enqueuePending: (state, { sessionId, want }) => {
                    const existing = state[sessionId] ?? { wantsExistence: false, wantsOutcome: false }
                    if (existing[want]) {
                        return state
                    }
                    return { ...state, [sessionId]: { ...existing, [want]: true } }
                },
                removePending: (state, { sessionIds }) => {
                    const next = { ...state }
                    for (const id of sessionIds) {
                        delete next[id]
                    }
                    return next
                },
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        checkRecordingInfo: ({ sessionId, includeOutcome }) => {
            const { recordingExistsStorage, outcomeBySessionId, pendingFetches } = values
            let scheduleFlush = false

            const existenceMissing = !(sessionId in recordingExistsStorage)
            if (existenceMissing && !pendingFetches[sessionId]?.wantsExistence) {
                actions.enqueuePending(sessionId, 'wantsExistence')
                scheduleFlush = true
            }

            if (includeOutcome) {
                const cached = outcomeBySessionId[sessionId]
                const outcomeMissing = cached === undefined || cached === 'error'
                if (outcomeMissing && !pendingFetches[sessionId]?.wantsOutcome) {
                    actions.enqueuePending(sessionId, 'wantsOutcome')
                    scheduleFlush = true
                }
            }

            if (scheduleFlush) {
                actions.flushPending()
            }
        },

        flushPending: async (_, breakpoint) => {
            await breakpoint(10)

            const allPending = Object.entries(values.pendingFetches)
            if (allPending.length === 0) {
                return
            }

            const batch = allPending.slice(0, BATCH_SIZE)
            const sessionIds = batch.map(([id]) => id)
            const existenceNeeded = batch.filter(([, want]) => want.wantsExistence).map(([id]) => id)
            const outcomeNeeded = batch.filter(([, want]) => want.wantsOutcome).map(([id]) => id)
            const includeOutcomes = outcomeNeeded.length > 0

            if (existenceNeeded.length > 0) {
                actions.recordExistence(
                    Object.fromEntries(existenceNeeded.map((id) => [id, RecordingExistsState.Loading]))
                )
            }

            try {
                const response = await api.recordings.batchCheckExists(sessionIds, { includeOutcomes })

                await breakpoint()

                if (existenceNeeded.length > 0) {
                    const updates: RecordingExistsStorage = {}
                    for (const id of existenceNeeded) {
                        updates[id] = response.results[id]
                            ? RecordingExistsState.Exists
                            : RecordingExistsState.NotExists
                    }
                    actions.recordExistence(updates)
                }

                if (outcomeNeeded.length > 0) {
                    const outcomeUpdates: Record<string, StoredOutcome> = {}
                    for (const id of outcomeNeeded) {
                        outcomeUpdates[id] = response.outcomes?.[id] ?? null
                    }
                    actions.recordOutcomes(outcomeUpdates)
                }

                actions.removePending(sessionIds)
            } catch {
                if (existenceNeeded.length > 0) {
                    const errorUpdates: RecordingExistsStorage = Object.fromEntries(
                        existenceNeeded.map((id) => [id, RecordingExistsState.Error])
                    )
                    actions.recordExistence(errorUpdates)
                }
                if (outcomeNeeded.length > 0) {
                    const failedOutcomes: Record<string, StoredOutcome> = Object.fromEntries(
                        outcomeNeeded.map((id) => [id, 'error' as const])
                    )
                    actions.recordOutcomes(failedOutcomes)
                }
                actions.removePending(sessionIds)
            }

            await breakpoint()
            if (Object.keys(values.pendingFetches).length > 0) {
                actions.flushPending()
            }
        },
    })),
    selectors({
        getRecordingExists: [
            (s) => [s.recordingExistsStorage],
            (storage: RecordingExistsStorage) =>
                (sessionId: string): boolean | undefined => {
                    const state = storage[sessionId]
                    if (state === RecordingExistsState.Exists) {
                        return true
                    }
                    if (state === RecordingExistsState.NotExists) {
                        return false
                    }
                    return undefined
                },
        ],
        isRecordingExistsLoading: [
            (s) => [s.recordingExistsStorage, s.pendingFetches],
            (storage: RecordingExistsStorage, pending: Record<string, PendingFetch>) =>
                (sessionId: string): boolean => {
                    if (pending[sessionId]?.wantsExistence) {
                        return true
                    }
                    return storage[sessionId] === RecordingExistsState.Loading
                },
        ],
        getSummaryOutcome: [
            (s) => [s.outcomeBySessionId],
            (storage: Record<string, StoredOutcome>) =>
                (sessionId: string): SummaryOutcome | null => {
                    const stored = storage[sessionId]
                    if (stored === undefined || stored === 'error' || stored === null) {
                        return null
                    }
                    return stored
                },
        ],
    }),
    permanentlyMount(),
])
