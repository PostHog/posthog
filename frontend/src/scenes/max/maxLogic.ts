import { captureException } from '@sentry/react'
import { shuffle } from 'd3'
import { createParser } from 'eventsource-parser'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { isHumanMessage, isVisualizationMessage } from 'scenes/max/utils'
import { projectLogic } from 'scenes/projectLogic'

import {
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessageType,
    FailureMessage,
    NodeKind,
    RefreshType,
    RootAssistantMessage,
    SuggestedQuestionsQuery,
} from '~/queries/schema'

import type { maxLogicType } from './maxLogicType'

export interface MaxLogicProps {
    sessionId: string
}

export type MessageStatus = 'loading' | 'completed' | 'error'

export type ThreadMessage = RootAssistantMessage & {
    status?: MessageStatus
}

const FAILURE_MESSAGE: FailureMessage = {
    type: AssistantMessageType.Failure,
    content: 'Oops! It looks like I’m having trouble generating this trends insight. Could you please try again?',
}

export const maxLogic = kea<maxLogicType>([
    path(['scenes', 'max', 'maxLogic']),
    props({} as MaxLogicProps),
    key(({ sessionId }) => sessionId),
    connect({
        values: [projectLogic, ['currentProject']],
    }),
    actions({
        askMax: (prompt: string) => ({ prompt }),
        setThreadLoaded: (testOnlyOverride = false) => ({ testOnlyOverride }),
        addMessage: (message: ThreadMessage) => ({ message }),
        replaceMessage: (index: number, message: ThreadMessage) => ({ index, message }),
        setMessageStatus: (index: number, status: ThreadMessage['status']) => ({ index, status }),
        setQuestion: (question: string) => ({ question }),
        setVisibleSuggestions: (suggestions: string[]) => ({ suggestions }),
        shuffleVisibleSuggestions: true,
        retryLastMessage: true,
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
                loadSuggestions: async ({ refresh }: { refresh: RefreshType }) => {
                    const response = await api.query<SuggestedQuestionsQuery>(
                        { kind: NodeKind.SuggestedQuestionsQuery },
                        undefined,
                        undefined,
                        refresh
                    )
                    return response.questions
                },
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        [projectLogic.actionTypes.updateCurrentProjectSuccess]: ({ payload }) => {
            if (payload?.product_description) {
                // Load suggestions anew after product description is changed on the project
                // Most important when description is set for the first time, but also when updated,
                // which is why we always want to load fresh suggestions here
                actions.loadSuggestions({ refresh: 'blocking' })
            }
        },
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
                    onEvent: ({ data, event }) => {
                        if (event === AssistantEventType.Message) {
                            const parsedResponse = parseResponse<RootAssistantMessage>(data)
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
                                    status: values.thread[newIndex].status,
                                })
                            }
                        } else if (event === AssistantEventType.Status) {
                            const parsedResponse = parseResponse<AssistantGenerationStatusEvent>(data)
                            if (!parsedResponse) {
                                return
                            }

                            if (parsedResponse.type === AssistantGenerationStatusType.GenerationError) {
                                actions.setMessageStatus(newIndex, 'error')
                            }
                        }
                    },
                })

                while (true) {
                    const { done, value } = await reader.read()

                    parser.feed(decoder.decode(value))

                    if (done) {
                        const generatedMessage = values.thread[newIndex]
                        if (generatedMessage && isVisualizationMessage(generatedMessage) && generatedMessage.plan) {
                            actions.setMessageStatus(newIndex, 'completed')
                        } else if (generatedMessage) {
                            actions.replaceMessage(newIndex, FAILURE_MESSAGE)
                        } else {
                            actions.addMessage({
                                ...FAILURE_MESSAGE,
                                status: 'completed',
                            })
                        }
                        break
                    }
                }
            } catch (e) {
                captureException(e)

                if (values.thread[newIndex]) {
                    actions.replaceMessage(newIndex, FAILURE_MESSAGE)
                } else {
                    actions.addMessage({
                        ...FAILURE_MESSAGE,
                        status: 'completed',
                    })
                }
            }

            actions.setThreadLoaded()
        },
        retryLastMessage: () => {
            const lastMessage = values.thread.filter(isHumanMessage).pop()
            if (lastMessage) {
                actions.askMax(lastMessage.content)
            }
        },
    })),
    selectors({
        sessionId: [(_, p) => [p.sessionId], (sessionId) => sessionId],
    }),
    afterMount(({ actions, values }) => {
        // We only load suggestions on mount if the product description is already set
        if (values.currentProject?.product_description) {
            // In this case we're fine with even really old cached values
            actions.loadSuggestions({ refresh: 'async_except_on_cache_miss' })
        }
    }),
])

/**
 * Parses the generation result from the API. Some generation chunks might be sent in batches.
 * @param response
 */
function parseResponse<T>(response: string): T | null | undefined {
    try {
        const parsed = JSON.parse(response)
        return parsed as T | null | undefined
    } catch {
        return null
    }
}
