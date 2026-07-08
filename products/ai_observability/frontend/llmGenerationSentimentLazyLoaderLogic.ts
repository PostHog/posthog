import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { chunk } from 'lib/utils/arrays'
import { teamLogic } from 'scenes/teamLogic'

import type { llmGenerationSentimentLazyLoaderLogicType } from './llmGenerationSentimentLazyLoaderLogicType'
import { fetchStoredGenerationSentiments, type GenerationSentimentLookup } from './sentimentQueries'
import type { GenerationSentiment } from './sentimentResults'
import { runWithConcurrency } from './utils'

const BATCH_MAX_SIZE = 100
const MAX_CONCURRENT_BATCHES = 2
const BATCH_TIMER_DISPOSABLE_KEY = 'generationSentimentBatchTimer'

export const llmGenerationSentimentLazyLoaderLogic = kea<llmGenerationSentimentLazyLoaderLogicType>([
    path(['products', 'ai_observability', 'frontend', 'llmGenerationSentimentLazyLoaderLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    actions({
        ensureGenerationSentimentLoaded: (lookup: GenerationSentimentLookup) => ({ lookup }),
        loadGenerationSentimentBatchSuccess: (
            results: Record<string, GenerationSentiment | null>,
            requestedKeys: string[]
        ) => ({ results, requestedKeys }),
        loadGenerationSentimentBatchFailure: (requestedKeys: string[]) => ({ requestedKeys }),
        clearLoadingGeneration: (key: string) => ({ key }),
    }),

    reducers({
        sentimentByGenerationKey: [
            {} as Record<string, GenerationSentiment | null>,
            {
                loadGenerationSentimentBatchSuccess: (state, { results, requestedKeys }) => {
                    const next = { ...state }

                    for (const key of requestedKeys) {
                        next[key] = results[key] ?? null
                    }

                    return next
                },
                loadGenerationSentimentBatchFailure: (state, { requestedKeys }) => {
                    const next = { ...state }

                    for (const key of requestedKeys) {
                        next[key] = null
                    }

                    return next
                },
            },
        ],

        loadingGenerationKeys: [
            new Set<string>(),
            {
                ensureGenerationSentimentLoaded: (state, { lookup }) => {
                    if (state.has(lookup.key)) {
                        return state
                    }

                    const next = new Set(state)
                    next.add(lookup.key)
                    return next
                },
                loadGenerationSentimentBatchSuccess: (state, { requestedKeys }) => {
                    const next = new Set(state)

                    for (const key of requestedKeys) {
                        next.delete(key)
                    }

                    return next
                },
                loadGenerationSentimentBatchFailure: (state, { requestedKeys }) => {
                    const next = new Set(state)

                    for (const key of requestedKeys) {
                        next.delete(key)
                    }

                    return next
                },
                clearLoadingGeneration: (state, { key }) => {
                    if (!state.has(key)) {
                        return state
                    }

                    const next = new Set(state)
                    next.delete(key)
                    return next
                },
            },
        ],
    }),

    selectors({
        isGenerationLoading: [
            (s) => [s.loadingGenerationKeys],
            (loadingGenerationKeys): ((key: string) => boolean) => {
                return (key: string) => loadingGenerationKeys.has(key)
            },
        ],
        getGenerationSentiment: [
            (s) => [s.sentimentByGenerationKey],
            (sentimentByGenerationKey): ((key: string) => GenerationSentiment | null | undefined) => {
                return (key: string) => sentimentByGenerationKey[key]
            },
        ],
    }),

    listeners(({ values, actions, cache }) => {
        return {
            ensureGenerationSentimentLoaded: ({ lookup }) => {
                if (values.sentimentByGenerationKey[lookup.key] !== undefined) {
                    actions.clearLoadingGeneration(lookup.key)
                    return
                }

                const pendingLookups = (cache.pendingLookups ??= new Map<string, GenerationSentimentLookup>()) as Map<
                    string,
                    GenerationSentimentLookup
                >
                pendingLookups.set(lookup.key, lookup)

                cache.disposables.add(() => {
                    const batchTimer = setTimeout(() => {
                        cache.disposables.dispose(BATCH_TIMER_DISPOSABLE_KEY)
                        void (async () => {
                            const pendingLookups = cache.pendingLookups as Map<string, GenerationSentimentLookup>
                            const allLookups = Array.from(pendingLookups.values())
                            cache.pendingLookups = new Map<string, GenerationSentimentLookup>()

                            if (!values.currentTeamId || allLookups.length === 0) {
                                actions.loadGenerationSentimentBatchFailure(allLookups.map((lookup) => lookup.key))
                                return
                            }

                            const chunks = chunk(allLookups, BATCH_MAX_SIZE)

                            await runWithConcurrency(chunks, MAX_CONCURRENT_BATCHES, async (batch) => {
                                const requestedKeys = batch.map((lookup) => lookup.key)

                                try {
                                    const results = await fetchStoredGenerationSentiments(batch)
                                    actions.loadGenerationSentimentBatchSuccess(results, requestedKeys)
                                } catch {
                                    actions.loadGenerationSentimentBatchFailure(requestedKeys)
                                }
                            })
                        })()
                    }, 0)

                    return () => clearTimeout(batchTimer)
                }, BATCH_TIMER_DISPOSABLE_KEY)
            },
        }
    }),
])
