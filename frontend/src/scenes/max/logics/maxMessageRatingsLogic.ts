import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import type { maxMessageRatingsLogicType } from './maxMessageRatingsLogicType'

export type MaxMessageRating = 'good' | 'bad'
export type MaxMessageRatingOrNull = MaxMessageRating | null

const RATING_STORAGE_KEY = 'posthog_ai_ratings'
const MAX_STORED_RATINGS = 1000

function safeReadRatingsFromStorage(): Record<string, MaxMessageRating> {
    try {
        const stored = localStorage.getItem(RATING_STORAGE_KEY)
        if (!stored) {
            return {}
        }
        const parsed: unknown = JSON.parse(stored)
        if (!parsed || typeof parsed !== 'object') {
            return {}
        }
        // Accepts { [traceId: string]: 'good' | 'bad' }
        const result: Record<string, MaxMessageRating> = {}
        for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
            if (value === 'good' || value === 'bad') {
                result[key] = value
            }
        }
        return result
    } catch {
        // Ignore storage errors
        return {}
    }
}

function safeWriteRatingsToStorage(ratings: Record<string, MaxMessageRating>): void {
    try {
        // Prune to MAX_STORED_RATINGS if exceeded (keep most recent by removing from the start)
        const entries = Object.entries(ratings)
        if (entries.length > MAX_STORED_RATINGS) {
            const pruned = Object.fromEntries(entries.slice(-MAX_STORED_RATINGS))
            localStorage.setItem(RATING_STORAGE_KEY, JSON.stringify(pruned))
        } else {
            localStorage.setItem(RATING_STORAGE_KEY, JSON.stringify(ratings))
        }
    } catch {
        // Ignore storage errors
    }
}

/**
 * Persists Max AI message ratings ("good"/"bad") keyed by trace ID.
 *
 * Ratings are hydrated lazily per-trace via `ensureLoadedForTraceId`, and also can be stored via `setRatingForTraceId`.
 */
export const maxMessageRatingsLogic = kea<maxMessageRatingsLogicType>([
    path(['scenes', 'max', 'logics', 'maxMessageRatingsLogic']),

    afterMount(({ actions }) => {
        // Hydrate all ratings once on mount so re-opening a chat reflects localStorage immediately,
        // even if individual message components don't call `ensureLoadedForTraceId` (or unmount before it runs).
        const ratings = safeReadRatingsFromStorage()
        for (const [traceId, rating] of Object.entries(ratings)) {
            actions.setRatingForTraceId({ traceId, rating })
        }
    }),

    actions({
        ensureLoadedForTraceId: (payload: { traceId: string }) => ({ traceId: payload.traceId.trim() }),
        setRatingForTraceId: (payload: { traceId: string; rating: MaxMessageRating }) => ({
            traceId: payload.traceId.trim(),
            rating: payload.rating,
        }),
        clearRatingForTraceId: (payload: { traceId: string }) => ({ traceId: payload.traceId.trim() }),
        clearAllRatings: true,
    }),

    reducers({
        ratingsByTraceId: [
            {} as Record<string, MaxMessageRating>,
            {
                setRatingForTraceId: (state, { traceId, rating }) => ({
                    ...state,
                    [traceId]: rating,
                }),
                clearRatingForTraceId: (state, { traceId }) => {
                    if (!(traceId in state)) {
                        return state
                    }
                    const next = { ...state }
                    delete next[traceId]
                    return next
                },
                clearAllRatings: () => ({}),
            },
        ],
        loadedTraceIds: [
            {} as Record<string, true>,
            {
                ensureLoadedForTraceId: (state, { traceId }) => ({
                    ...state,
                    [traceId]: true,
                }),
                clearAllRatings: () => ({}),
            },
        ],
    }),

    selectors({
        ratingForTraceId: [
            (s) => [s.ratingsByTraceId],
            (ratingsByTraceId: Record<string, MaxMessageRating>) => {
                return (traceId: string | null | undefined): MaxMessageRatingOrNull => {
                    if (!traceId) {
                        return null
                    }
                    return ratingsByTraceId[traceId] ?? null
                }
            },
        ],
        isLoadedForTraceId: [
            (s) => [s.loadedTraceIds],
            (loadedTraceIds: Record<string, true>) => {
                return (traceId: string | null | undefined): boolean => {
                    if (!traceId) {
                        return true
                    }
                    return !!loadedTraceIds[traceId]
                }
            },
        ],
    }),

    listeners(({ values, actions }) => ({
        ensureLoadedForTraceId: ({ traceId }) => {
            // Only read storage once per traceId (and only if not already present in state).
            if (!traceId || values.loadedTraceIds[traceId]) {
                return
            }

            const ratings = safeReadRatingsFromStorage()
            const rating = ratings[traceId]
            if (rating) {
                actions.setRatingForTraceId({ traceId, rating })
            }
            // Mark as loaded even if absent, to avoid repeated JSON.parse churn.
            // (Handled via loadedTraceIds reducer on ensureLoadedForTraceId)
        },

        setRatingForTraceId: ({ traceId, rating }) => {
            if (!traceId) {
                return
            }
            if (rating !== 'good' && rating !== 'bad') {
                return
            }

            const current = safeReadRatingsFromStorage()
            safeWriteRatingsToStorage({
                ...current,
                [traceId]: rating,
            })
        },

        clearRatingForTraceId: ({ traceId }) => {
            if (!traceId) {
                return
            }

            const current = safeReadRatingsFromStorage()
            delete current[traceId]
            safeWriteRatingsToStorage(current)
        },

        clearAllRatings: () => {
            safeWriteRatingsToStorage({})
        },
    })),
])
