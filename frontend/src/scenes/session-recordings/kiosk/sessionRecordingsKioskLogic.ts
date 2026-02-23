import { actions, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { NodeKind, RecordingsQuery } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, SessionRecordingType } from '~/types'

import type { sessionRecordingsKioskLogicType } from './sessionRecordingsKioskLogicType'

const KIOSK_PLAYED_IDS_KEY = 'kiosk_played_ids'
const SOFT_REFRESH_AFTER_RECORDINGS = 10
const HARD_REFRESH_AFTER_RECORDINGS = 50
const MAX_RECORDING_PLAY_TIME_MS = 5 * 60 * 1000 // 5 minutes
const RETRY_DELAY_MS = 5000

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
        // Silently ignore - kiosk mode is unattended so toasts aren't useful.
        // Failure is non-critical: playback continues, just won't persist across refreshes.
    }
}

export interface KioskFilters {
    visitedPage: string | null
    dateFrom: string
    minDurationSeconds: number
}

const DEFAULT_FILTERS: KioskFilters = {
    visitedPage: null,
    dateFrom: '-30d',
    minDurationSeconds: 5,
}

export const sessionRecordingsKioskLogic = kea<sessionRecordingsKioskLogicType>([
    path(['scenes', 'session-recordings', 'kiosk', 'sessionRecordingsKioskLogic']),
    actions({
        setCurrentRecordingId: (id: string | null) => ({ id }),
        markRecordingPlayed: (id: string) => ({ id }),
        advanceToNextRecording: true,
        setFilters: (filters: Partial<KioskFilters>) => ({ filters }),
        startPlayback: true,
        resetPlayback: true,
        resetPlayedRecordings: true,
    }),
    reducers({
        started: [
            false,
            {
                startPlayback: () => true,
                resetPlayback: () => false,
            },
        ],
        filters: [
            DEFAULT_FILTERS as KioskFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
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
                loadRecordingsSuccess: () => 0,
            },
        ],
        totalPlayedCount: [
            0,
            {
                markRecordingPlayed: (state) => state + 1,
                startPlayback: () => 0,
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
                resetPlayedRecordings: () => [],
            },
        ],
    }),
    loaders(({ values }) => ({
        recordings: [
            [] as SessionRecordingType[],
            {
                loadRecordings: async () => {
                    const { visitedPage, dateFrom, minDurationSeconds } = values.filters

                    const query: RecordingsQuery = {
                        kind: NodeKind.RecordingsQuery,
                        order: 'start_time',
                        order_direction: 'DESC',
                        date_from: dateFrom || '-30d',
                        date_to: null,
                        limit: 100,
                        filter_test_accounts: true,
                        properties: visitedPage
                            ? [
                                  {
                                      type: PropertyFilterType.Recording,
                                      key: 'visited_page',
                                      operator: PropertyOperator.IContains,
                                      value: [visitedPage],
                                  },
                              ]
                            : [],
                        having_predicates:
                            minDurationSeconds > 0
                                ? [
                                      {
                                          type: PropertyFilterType.Recording,
                                          key: 'active_seconds',
                                          value: minDurationSeconds,
                                          operator: PropertyOperator.GreaterThan,
                                      },
                                  ]
                                : [],
                    }
                    const response = await api.recordings.list(query)
                    return response.results
                },
            },
        ],
    })),
    selectors({
        isConfigured: [(s) => [s.started], (started): boolean => started],
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
        hasRecordings: [(s) => [s.recordings], (recordings): boolean => recordings.length > 0],
    }),
    listeners(({ actions, values }) => ({
        markRecordingPlayed: () => {
            savePlayedRecordingIds(values.playedRecordingIds)
        },
        startPlayback: () => {
            actions.loadRecordings()
        },
        resetPlayedRecordings: () => {
            sessionStorage.removeItem(KIOSK_PLAYED_IDS_KEY)
        },
        advanceToNextRecording: () => {
            clearStuckTimeout()

            if (values.currentRecordingId) {
                actions.markRecordingPlayed(values.currentRecordingId)
            }

            // Hard page reload periodically to free memory from rrweb replayers
            if (values.totalPlayedCount >= HARD_REFRESH_AFTER_RECORDINGS) {
                window.location.reload()
                return
            }

            const needsSoftRefresh = values.playedCountSinceRefresh >= SOFT_REFRESH_AFTER_RECORDINGS
            const next = values.nextRecording

            if (needsSoftRefresh || !next) {
                // Fetch fresh recordings from the API. Clear currentRecordingId so
                // loadRecordingsSuccess knows to pick the next one.
                actions.setCurrentRecordingId(null)
                actions.loadRecordings()
            } else {
                actions.setCurrentRecordingId(next.id)
            }
        },
        loadRecordingsSuccess: () => {
            if (!values.currentRecordingId) {
                const first = values.unplayedRecordings[0]
                if (first) {
                    actions.setCurrentRecordingId(first.id)
                } else if (values.recordings.length > 0) {
                    // API returned only recordings we've already seen — reset and loop
                    actions.resetPlayedRecordings()
                    actions.setCurrentRecordingId(values.recordings[0].id)
                }
            }
        },
        loadRecordingsFailure: () => {
            setTimeout(() => {
                actions.loadRecordings()
            }, RETRY_DELAY_MS)
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

    actionToUrl(({ values }) => ({
        resetPlayback: () => {
            const params: Record<string, string> = {}
            if (values.filters.visitedPage) {
                params.visited_page = values.filters.visitedPage
            }
            if (values.filters.dateFrom && values.filters.dateFrom !== '-30d') {
                params.date_from = values.filters.dateFrom
            }
            if (values.filters.minDurationSeconds !== DEFAULT_FILTERS.minDurationSeconds) {
                params.min_duration = String(values.filters.minDurationSeconds)
            }
            return [urls.replayKiosk(), params, undefined, { replace: true }]
        },
        startPlayback: () => {
            const params: Record<string, string> = { play: '1' }
            if (values.filters.visitedPage) {
                params.visited_page = values.filters.visitedPage
            }
            if (values.filters.dateFrom && values.filters.dateFrom !== '-30d') {
                params.date_from = values.filters.dateFrom
            }
            if (values.filters.minDurationSeconds !== DEFAULT_FILTERS.minDurationSeconds) {
                params.min_duration = String(values.filters.minDurationSeconds)
            }
            return [urls.replayKiosk(), params, undefined, { replace: true }]
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.replayKiosk()]: (_, searchParams) => {
            const visitedPage = searchParams.visited_page || null
            const dateFrom = searchParams.date_from || '-30d'
            const minDurationSeconds = searchParams.min_duration
                ? Number(searchParams.min_duration)
                : DEFAULT_FILTERS.minDurationSeconds

            if (
                visitedPage !== values.filters.visitedPage ||
                dateFrom !== values.filters.dateFrom ||
                minDurationSeconds !== values.filters.minDurationSeconds
            ) {
                actions.setFilters({ visitedPage, dateFrom, minDurationSeconds })
            }

            if (searchParams.play === '1' && !values.started) {
                actions.startPlayback()
            }
        },
    })),

    beforeUnmount(() => {
        clearStuckTimeout()
    }),
])
