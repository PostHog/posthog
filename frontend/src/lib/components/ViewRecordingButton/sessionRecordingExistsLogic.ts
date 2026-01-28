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

export const sessionRecordingExistsLogic = kea<sessionRecordingExistsLogicType>([
    path(['lib', 'components', 'ViewRecordingButton', 'sessionRecordingExistsLogic']),
    actions({
        checkRecordingExists: (sessionId: string) => ({ sessionId }),
        updateRecordingExistsStorage: (updates: RecordingExistsStorage) => ({ updates }),
        fetchAllPendingChecks: true,
    }),
    reducers({
        recordingExistsStorage: [
            {} as RecordingExistsStorage, // Choosing not to persist here as we cache on the BE, I don't want to kill client memory
            {
                updateRecordingExistsStorage: (state, { updates }) => ({
                    ...state,
                    ...updates,
                }),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        checkRecordingExists: ({ sessionId }) => {
            const { recordingExistsStorage } = values

            if (sessionId in recordingExistsStorage) {
                return
            }

            actions.updateRecordingExistsStorage({ [sessionId]: RecordingExistsState.Pending })
            actions.fetchAllPendingChecks()
        },

        fetchAllPendingChecks: async (_, breakpoint) => {
            await breakpoint(10)

            const pendingSessionIds = values.pendingSessionIds
            if (pendingSessionIds.length === 0) {
                return
            }

            const toCheck = pendingSessionIds.slice(0, 100)

            actions.updateRecordingExistsStorage(
                Object.fromEntries(toCheck.map((id: string) => [id, RecordingExistsState.Loading]))
            )

            try {
                const response = await api.recordings.batchCheckExists(toCheck)

                await breakpoint()

                const updates: RecordingExistsStorage = {}
                for (const sessionId of toCheck) {
                    updates[sessionId] = response.results[sessionId]
                        ? RecordingExistsState.Exists
                        : RecordingExistsState.NotExists
                }
                actions.updateRecordingExistsStorage(updates)
            } catch {
                actions.updateRecordingExistsStorage(
                    Object.fromEntries(toCheck.map((id: string) => [id, RecordingExistsState.Error]))
                )
            }

            await breakpoint()
            if (values.pendingSessionIds.length > 0) {
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
    }),
    permanentlyMount(),
])
