import { shuffle } from 'd3'
import { createParser } from 'eventsource-parser'
import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { AssistantMessageType, NodeKind, RootAssistantMessage, SuggestedQuestionsQuery } from '~/queries/schema'

import type { maxLogicType } from './maxLogicType'

export interface MaxLogicProps {
    sessionId: string
}

export type MessageStatus = 'loading' | 'completed' | 'error'

export type ThreadMessage = RootAssistantMessage & {
    status?: MessageStatus
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
                    const response = await api.query<SuggestedQuestionsQuery>(
                        { kind: NodeKind.SuggestedQuestionsQuery },
                        undefined,
                        undefined,
                        'async_except_on_cache_miss'
                    )
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
            actions.addMessage({ type: AssistantMessageType.Human, content: prompt })
            const newIndex = values.thread.length

            try {
                const response = await api.chat({
                    session_id: props.sessionId,
                    messages: values.thread.map(({ status, ...message }) => message),
                })
                const reader = response.body?.getReader()

                if (!reader) {
                    return
                }

                const decoder = new TextDecoder()

                let firstChunk = true

                const parser = createParser({
                    onEvent: (event) => {
                        const parsedResponse = parseResponse(event.data)

                        if (!parsedResponse) {
                            return
                        }

                        if (firstChunk) {
                            firstChunk = false

                            if (parsedResponse) {
                                actions.addMessage({ ...parsedResponse, status: 'loading' })
                            }
                        } else if (parsedResponse) {
                            actions.replaceMessage(newIndex, {
                                ...parsedResponse,
                                status: 'loading',
                            })
                        }
                    },
                })

                while (true) {
                    const { done, value } = await reader.read()

                    parser.feed(decoder.decode(value))

                    if (done) {
                        actions.setMessageStatus(newIndex, 'completed')
                        break
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
function parseResponse(response: string): RootAssistantMessage | null | undefined {
    try {
        const parsed = JSON.parse(response)
        return parsed as RootAssistantMessage | null | undefined
    } catch {
        return null
    }
}
