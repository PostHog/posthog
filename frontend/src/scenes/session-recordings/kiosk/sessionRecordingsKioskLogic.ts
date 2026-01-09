import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind, RecordingsQuery } from '~/queries/schema/schema-general'
import { SessionRecordingType } from '~/types'

import type { sessionRecordingsKioskLogicType } from './sessionRecordingsKioskLogicType'

const KIOSK_PLAYED_IDS_KEY = 'kiosk_played_ids'
const REFRESH_AFTER_RECORDINGS = 10
const MAX_RECORDING_PLAY_TIME_MS = 5 * 60 * 1000 // 5 minutes

let stuckRecordingTimeout: ReturnType<typeof setTimeout> | null = null

function clearStuckTimeout(): void {
    if (stuckRecordingTimeout) {
        clearTimeout(stuckRecordingTimeout)
        stuckRecordingTimeout = null
    }
}

function getPlayedRecordingIds(): string[] {
    try {
        const stored = sessionStorage.getItem(KIOSK_PLAYED_IDS_KEY)
        return stored ? JSON.parse(stored) : []
    } catch {
        return []
    }
}

function savePlayedRecordingIds(ids: string[]): void {
    try {
        sessionStorage.setItem(KIOSK_PLAYED_IDS_KEY, JSON.stringify(ids))
    } catch {
        // sessionStorage might be full or disabled
    }
}

export const sessionRecordingsKioskLogic = kea<sessionRecordingsKioskLogicType>([
    path(['scenes', 'session-recordings', 'kiosk', 'sessionRecordingsKioskLogic']),
    actions({
        setCurrentRecordingId: (id: string | null) => ({ id }),
        markRecordingPlayed: (id: string) => ({ id }),
        advanceToNextRecording: true,
        triggerRefresh: true,
        clearPlayedRecordingsAndRestart: true,
    }),
    reducers({
        currentRecordingId: [
            null as string | null,
            {
                setCurrentRecordingId: (_, { id }) => id,
            },
        ],
        playedCountSinceRefresh: [
            0,
            {
                markRecordingPlayed: (state) => state + 1,
            },
        ],
        playedRecordingIds: [
            getPlayedRecordingIds(),
            {
                markRecordingPlayed: (state, { id }) => {
                    if (state.includes(id)) {
                        return state
                    }
                    return [...state, id]
                },
            },
        ],
    }),
    loaders(() => ({
        recordings: [
            [] as SessionRecordingType[],
            {
                loadRecordings: async () => {
                    const query: RecordingsQuery = {
                        kind: NodeKind.RecordingsQuery,
                        order: 'start_time',
                        order_direction: 'DESC',
                        date_from: '-30d',
                        date_to: null,
                        limit: 100,
                    }
                    const response = await api.recordings.list(query)
                    return response.results
                },
            },
        ],
    })),
    selectors({
        unplayedRecordings: [
            (s) => [s.recordings, s.playedRecordingIds],
            (recordings, playedRecordingIds): SessionRecordingType[] =>
                recordings.filter((r) => !playedRecordingIds.includes(r.id)),
        ],
        currentRecording: [
            (s) => [s.recordings, s.currentRecordingId],
            (recordings, currentRecordingId): SessionRecordingType | null =>
                recordings.find((r) => r.id === currentRecordingId) ?? null,
        ],
        nextRecording: [
            (s) => [s.unplayedRecordings, s.currentRecordingId],
            (unplayedRecordings, currentRecordingId): SessionRecordingType | null => {
                if (!currentRecordingId) {
                    return unplayedRecordings[0] ?? null
                }
                const currentIndex = unplayedRecordings.findIndex((r) => r.id === currentRecordingId)
                return unplayedRecordings[currentIndex + 1] ?? unplayedRecordings[0] ?? null
            },
        ],
        hasRecordings: [(s) => [s.unplayedRecordings], (unplayedRecordings): boolean => unplayedRecordings.length > 0],
    }),
    listeners(({ actions, values }) => ({
        markRecordingPlayed: () => {
            savePlayedRecordingIds(values.playedRecordingIds)
        },
        advanceToNextRecording: () => {
            clearStuckTimeout()

            if (values.currentRecordingId) {
                actions.markRecordingPlayed(values.currentRecordingId)
            }

            if (values.playedCountSinceRefresh >= REFRESH_AFTER_RECORDINGS) {
                actions.triggerRefresh()
                return
            }

            const next = values.nextRecording
            if (next) {
                actions.setCurrentRecordingId(next.id)
            } else {
                actions.clearPlayedRecordingsAndRestart()
            }
        },
        triggerRefresh: () => {
            clearStuckTimeout()
            window.location.reload()
        },
        clearPlayedRecordingsAndRestart: () => {
            sessionStorage.removeItem(KIOSK_PLAYED_IDS_KEY)
            actions.triggerRefresh()
        },
        loadRecordingsSuccess: () => {
            if (!values.currentRecordingId) {
                const first = values.unplayedRecordings[0]
                if (first) {
                    actions.setCurrentRecordingId(first.id)
                } else {
                    actions.clearPlayedRecordingsAndRestart()
                }
            }
        },
        setCurrentRecordingId: ({ id }) => {
            clearStuckTimeout()

            if (id) {
                stuckRecordingTimeout = setTimeout(() => {
                    actions.advanceToNextRecording()
                }, MAX_RECORDING_PLAY_TIME_MS)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRecordings()
    }),
    beforeUnmount(() => {
        clearStuckTimeout()
    }),
])
