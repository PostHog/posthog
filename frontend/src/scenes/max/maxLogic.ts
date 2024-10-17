import { shuffle } from 'd3'
import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { ExperimentalAITrendsQuery, NodeKind, SuggestedQuestionsQuery } from '~/queries/schema'

import type { maxLogicType } from './maxLogicType'

export interface MaxLogicProps {
    sessionId: string
}

export interface TrendGenerationResult {
    reasoning_steps?: string[]
    answer?: ExperimentalAITrendsQuery
}

export interface ThreadMessage {
    role: 'user' | 'assistant'
    content?: string | TrendGenerationResult
    status?: 'loading' | 'completed' | 'error'
}

export const maxLogic = kea<maxLogicType>([
    path(['scenes', 'max', 'maxLogic']),
    props({} as MaxLogicProps),
    key(({ sessionId }) => sessionId),
    actions({
        askMax: (prompt: string) => ({ prompt }),
        setThreadLoaded: (testOnlyOverride = false) => ({ testOnlyOverride }),
        addMessage: (message: ThreadMessage) => ({ message }),
        replaceMessage: (index: number, message: ThreadMessage) => ({ index, message }),
        setMessageStatus: (index: number, status: ThreadMessage['status']) => ({ index, status }),
        setQuestion: (question: string) => ({ question }),
        setVisibleSuggestions: (suggestions: string[]) => ({ suggestions }),
        shuffleVisibleSuggestions: true,
    }),
    reducers({
        question: [
            '',
            {
                setQuestion: (_, { question }) => question,
                askMax: () => '',
            },
        ],
        thread: [
            [] as ThreadMessage[],
            {
                addMessage: (state, { message }) => [...state, message],
                replaceMessage: (state, { message, index }) => [
                    ...state.slice(0, index),
                    message,
                    ...state.slice(index + 1),
                ],
                setMessageStatus: (state, { index, status }) => [
                    ...state.slice(0, index),
                    {
                        ...state[index],
                        status,
                    },
                    ...state.slice(index + 1),
                ],
            },
        ],
        threadLoading: [
            false,
            {
                askMax: () => true,
                setThreadLoaded: (_, { testOnlyOverride }) => testOnlyOverride,
            },
        ],
        wasSuggestionLoadingInitiated: [
            false,
            {
                loadSuggestions: () => true,
            },
        ],
        visibleSuggestions: [
            null as string[] | null,
            {
                setVisibleSuggestions: (_, { suggestions }) => suggestions,
            },
        ],
    }),
    loaders({
        allSuggestions: [
            null as string[] | null,
            {
                loadSuggestions: async () => {
                    const response = await api.query<SuggestedQuestionsQuery>({
                        kind: NodeKind.SuggestedQuestionsQuery,
                    })
                    return response.questions
                },
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        loadSuggestionsSuccess: () => {
            actions.shuffleVisibleSuggestions()
        },
        shuffleVisibleSuggestions: () => {
            if (!values.allSuggestions) {
                throw new Error('No question suggestions to shuffle')
            }
            const allSuggestionsWithoutCurrentlyVisible = values.allSuggestions.filter(
                (suggestion) => !values.visibleSuggestions?.includes(suggestion)
            )
            if (!process.env.STORYBOOK) {
                // Randomize order, except in Storybook where we want to keep the order consistent for snapshots
                shuffle(allSuggestionsWithoutCurrentlyVisible)
            }
            actions.setVisibleSuggestions(allSuggestionsWithoutCurrentlyVisible.slice(0, 3))
        },
        askMax: async ({ prompt }) => {
            actions.addMessage({ role: 'user', content: prompt })
            const newIndex = values.thread.length

            try {
                const response = await api.chat({
                    session_id: props.sessionId,
                    messages: values.thread.map(({ role, content }) => ({
                        role,
                        content: typeof content === 'string' ? content : JSON.stringify(content),
                    })),
                })
                const reader = response.body?.getReader()
                const decoder = new TextDecoder()

                if (reader) {
                    let firstChunk = true

                    while (true) {
                        const { done, value } = await reader.read()
                        if (done) {
                            actions.setMessageStatus(newIndex, 'completed')
                            break
                        }

                        const text = decoder.decode(value)
                        const parsedResponse = parseResponse(text)

                        if (firstChunk) {
                            firstChunk = false

                            if (parsedResponse) {
                                actions.addMessage({ role: 'assistant', content: parsedResponse, status: 'loading' })
                            }
                        } else if (parsedResponse) {
                            actions.replaceMessage(newIndex, {
                                role: 'assistant',
                                content: parsedResponse,
                                status: 'loading',
                            })
                        }
                    }
                }
            } catch {
                actions.setMessageStatus(values.thread.length - 1 === newIndex ? newIndex : newIndex - 1, 'error')
            }

            actions.setThreadLoaded()
        },
    })),
    selectors({
        sessionId: [(_, p) => [p.sessionId], (sessionId) => sessionId],
    }),
])

/**
 * Parses the generation result from the API. Some generation chunks might be sent in batches.
 * @param response
 */
function parseResponse(response: string, recursive = true): TrendGenerationResult | null {
    try {
        const parsed = JSON.parse(response)
        return parsed as TrendGenerationResult
    } catch {
        if (!recursive) {
            return null
        }

        const results: [number, number][] = []
        let pair: [number, number] = [0, 0]
        let seq = 0

        for (let i = 0; i < response.length; i++) {
            const char = response[i]

            if (char === '{') {
                if (seq === 0) {
                    pair[0] = i
                }

                seq += 1
            }

            if (char === '}') {
                seq -= 1
                if (seq === 0) {
                    pair[1] = i
                }
            }

            if (seq === 0) {
                results.push(pair)
                pair = [0, 0]
            }
        }

        const lastPair = results.pop()

        if (lastPair) {
            const [left, right] = lastPair
            return parseResponse(response.slice(left, right + 1), false)
        }

        return null
    }
}
