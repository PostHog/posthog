import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import type { sessionRecordingExistsLogicType } from './sessionRecordingExistsLogicType'

export enum RecordingExistsState {
    Pending = 'pending',
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

export const sessionRecordingExistsLogic = kea<sessionRecordingExistsLogicType>([
    path(['lib', 'components', 'ViewRecordingButton', 'sessionRecordingExistsLogic']),
    actions({
        checkRecordingExists: (sessionId: string, options?: { includeOutcome?: boolean }) => ({
            sessionId,
            includeOutcome: !!options?.includeOutcome,
        }),
        markOutcomeWanted: (sessionId: string) => ({ sessionId }),
        updateRecordingExistsStorage: (updates: RecordingExistsStorage) => ({ updates }),
        recordOutcomes: (outcomes: Record<string, StoredOutcome>) => ({ outcomes }),
        fetchAllPendingChecks: true,
    }),
    reducers({
        recordingExistsStorage: [
            {} as RecordingExistsStorage,
            {
                updateRecordingExistsStorage: (state, { updates }) => ({
                    ...state,
                    ...updates,
                }),
            },
        ],
        outcomeBySessionId: [
            {} as Record<string, StoredOutcome>,
            {
                recordOutcomes: (state, { outcomes }) => ({ ...state, ...outcomes }),
            },
        ],
        outcomeWantedSessionIds: [
            {} as Record<string, true>,
            {
                markOutcomeWanted: (state, { sessionId }) =>
                    state[sessionId] ? state : { ...state, [sessionId]: true },
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        checkRecordingExists: ({ sessionId, includeOutcome }) => {
            const { recordingExistsStorage, outcomeBySessionId } = values
            let scheduleFlush = false

            if (includeOutcome) {
                const cached = outcomeBySessionId[sessionId]
                if (cached === undefined || cached === 'error') {
                    actions.markOutcomeWanted(sessionId)
                    scheduleFlush = true
                }
            }

            if (!(sessionId in recordingExistsStorage)) {
                actions.updateRecordingExistsStorage({ [sessionId]: RecordingExistsState.Pending })
                scheduleFlush = true
            }

            if (scheduleFlush) {
                actions.fetchAllPendingChecks()
            }
        },

        fetchAllPendingChecks: async (_, breakpoint) => {
            await breakpoint(10)

            const pendingExistenceIds = values.pendingSessionIds
            const outcomeOnlyIds = values.pendingOutcomeOnlyIds
            const toCheck = pendingExistenceIds.slice(0, 100)
            const wantedOutcomes = values.outcomeWantedSessionIds

            const remainingSlots = Math.max(0, 100 - toCheck.length)
            const outcomeOnlyToFetch = outcomeOnlyIds.slice(0, remainingSlots)

            const sessionIds = [...toCheck, ...outcomeOnlyToFetch]
            if (sessionIds.length === 0) {
                return
            }

            const includeOutcomes = toCheck.some((id: string) => wantedOutcomes[id]) || outcomeOnlyToFetch.length > 0

            if (toCheck.length > 0) {
                actions.updateRecordingExistsStorage(
                    Object.fromEntries(toCheck.map((id: string) => [id, RecordingExistsState.Loading]))
                )
            }

            try {
                const response = await api.recordings.batchCheckExists(sessionIds, { includeOutcomes })

                await breakpoint()

                if (toCheck.length > 0) {
                    const updates: RecordingExistsStorage = {}
                    for (const sessionId of toCheck) {
                        updates[sessionId] = response.results[sessionId]
                            ? RecordingExistsState.Exists
                            : RecordingExistsState.NotExists
                    }
                    actions.updateRecordingExistsStorage(updates)
                }

                if (includeOutcomes) {
                    const outcomeUpdates: Record<string, StoredOutcome> = {}
                    for (const sessionId of sessionIds) {
                        if (!wantedOutcomes[sessionId] && !outcomeOnlyToFetch.includes(sessionId)) {
                            continue
                        }
                        outcomeUpdates[sessionId] = response.outcomes?.[sessionId] ?? null
                    }
                    if (Object.keys(outcomeUpdates).length > 0) {
                        actions.recordOutcomes(outcomeUpdates)
                    }
                }
            } catch {
                if (toCheck.length > 0) {
                    actions.updateRecordingExistsStorage(
                        Object.fromEntries(toCheck.map((id: string) => [id, RecordingExistsState.Error]))
                    )
                }
                if (includeOutcomes) {
                    const failedOutcomes: Record<string, StoredOutcome> = {}
                    for (const sessionId of sessionIds) {
                        if (wantedOutcomes[sessionId] || outcomeOnlyToFetch.includes(sessionId)) {
                            failedOutcomes[sessionId] = 'error'
                        }
                    }
                    if (Object.keys(failedOutcomes).length > 0) {
                        actions.recordOutcomes(failedOutcomes)
                    }
                }
            }

            await breakpoint()
            if (values.pendingSessionIds.length > 0 || values.pendingOutcomeOnlyIds.length > 0) {
                actions.fetchAllPendingChecks()
            }
        },
    })),
    selectors({
        pendingSessionIds: [
            (s) => [s.recordingExistsStorage],
            (storage: RecordingExistsStorage): string[] =>
                Object.entries(storage)
                    .filter(([_, state]) => state === RecordingExistsState.Pending)
                    .map(([id]) => id),
        ],
        pendingOutcomeOnlyIds: [
            (s) => [s.outcomeWantedSessionIds, s.outcomeBySessionId, s.recordingExistsStorage],
            (
                wanted: Record<string, true>,
                outcomes: Record<string, StoredOutcome>,
                storage: RecordingExistsStorage
            ): string[] =>
                Object.keys(wanted).filter((id) => {
                    const stored = outcomes[id]
                    const needsOutcome = stored === undefined || stored === 'error'
                    const existencePending =
                        storage[id] === RecordingExistsState.Pending || storage[id] === RecordingExistsState.Loading
                    return needsOutcome && !existencePending
                }),
        ],
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
            (s) => [s.recordingExistsStorage],
            (storage: RecordingExistsStorage) =>
                (sessionId: string): boolean => {
                    const state = storage[sessionId]
                    return state === RecordingExistsState.Pending || state === RecordingExistsState.Loading
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
