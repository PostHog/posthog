import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import type { maxMessageRatingsLogicType } from './maxMessageRatingsLogicType'

export type MaxMessageRating = 'good' | 'bad'
export type MaxMessageRatingOrNull = MaxMessageRating | null

const MAX_STORED_RATINGS = 1000

/**
 * Persists Max AI message ratings ("good"/"bad") keyed by trace ID.
 *
 * Uses Kea's localStorage plugin for automatic persistence.
 */
export const maxMessageRatingsLogic = kea<maxMessageRatingsLogicType>([
    path(['scenes', 'max', 'logics', 'maxMessageRatingsLogic']),

    actions({
        setRatingForTraceId: (payload: { traceId: string; rating: MaxMessageRating }) => ({
            traceId: payload.traceId.trim(),
            rating: payload.rating,
        }),
        clearRatingForTraceId: (payload: { traceId: string }) => ({ traceId: payload.traceId.trim() }),
        clearAllRatings: true,
        pruneOldRatings: true,
    }),

    reducers({
        ratingsByTraceId: [
            {} as Record<string, MaxMessageRating>,
            { persist: true, storageKey: 'posthog_ai_ratings' },
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
                pruneOldRatings: (state) => {
                    const entries = Object.entries(state)
                    if (entries.length <= MAX_STORED_RATINGS) {
                        return state
                    }
                    return Object.fromEntries(entries.slice(-MAX_STORED_RATINGS))
                },
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
    }),

    listeners(({ actions, values }) => ({
        setRatingForTraceId: () => {
            // Prune old ratings if we've exceeded the limit
            if (Object.keys(values.ratingsByTraceId).length > MAX_STORED_RATINGS) {
                actions.pruneOldRatings()
            }
        },
    })),
])
