import { shuffle } from 'd3'
import { createParser } from 'eventsource-parser'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { uuid } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import posthog from 'posthog-js'
import { projectLogic } from 'scenes/projectLogic'
import { maxSettingsLogic } from 'scenes/settings/environment/maxSettingsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { actionsModel } from '~/models/actionsModel'
import {
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessageType,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    RootAssistantMessage,
} from '~/queries/schema/schema-assistant-messages'
import { NodeKind, RefreshType, SuggestedQuestionsQuery } from '~/queries/schema/schema-general'
import { Conversation, SidePanelTab } from '~/types'

import { maxGlobalLogic } from './maxGlobalLogic'
import type { maxLogicType } from './maxLogicType'
import {
    isAssistantMessage,
    isAssistantToolCallMessage,
    isHumanMessage,
    isReasoningMessage,
    isVisualizationMessage,
} from './utils'

export interface MaxLogicProps {
    conversationId?: string
}

export type MessageStatus = 'loading' | 'completed' | 'error'

export type ThreadMessage = RootAssistantMessage & {
    status: MessageStatus
}

const FAILURE_MESSAGE: FailureMessage & ThreadMessage = {
    type: AssistantMessageType.Failure,
    content: 'Oops! It looks like I’m having trouble answering this. Could you please try again?',
    status: 'completed',
}

export const maxLogic = kea<maxLogicType>([
    path(['scenes', 'max', 'maxLogic']),
    props({} as MaxLogicProps),
    key(({ conversationId }) => conversationId || 'new-conversation'),
    connect(() => ({
        values: [
            projectLogic,
            ['currentProject'],
            maxGlobalLogic,
            ['dataProcessingAccepted', 'toolMap', 'tools'],
            maxSettingsLogic,
            ['coreMemory'],
            // Actions are lazy-loaded. In order to display their names in the UI, we're loading them here.
            actionsModel({ params: 'include_count=1' }),
            ['actions'],
        ],
    })),
    actions({
        askMax: (prompt: string, generationAttempt: number = 0) => ({ prompt, generationAttempt }),
        stopGeneration: true,
        setThreadLoaded: (testOnlyOverride = false) => ({ testOnlyOverride }),
        addMessage: (message: ThreadMessage) => ({ message }),
        replaceMessage: (index: number, message: ThreadMessage) => ({ index, message }),
        setMessageStatus: (index: number, status: MessageStatus) => ({ index, status }),
        setQuestion: (question: string) => ({ question }),
        setVisibleSuggestions: (suggestions: string[]) => ({ suggestions }),
        shuffleVisibleSuggestions: true,
        retryLastMessage: true,
        scrollThreadToBottom: true,
        setConversation: (conversation: Conversation) => ({ conversation }),
        setTraceId: (traceId: string) => ({ traceId }),
        resetThread: true,
        cleanThread: true,
        startNewConversation: true,
    }),
    reducers({
        question: [
            '',
            {
                setQuestion: (_, { question }) => question,
                askMax: () => '',
                cleanThread: () => '',
            },
        ],
        conversation: [
            (_, props) => (props.conversationId ? ({ id: props.conversationId } as Conversation) : null),
            {
                setConversation: (_, { conversation }) => conversation,
                cleanThread: () => null,
            },
        ],
        threadRaw: [
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
                resetThread: (state) => state.filter((message) => !isReasoningMessage(message)),
                cleanThread: () => [] as ThreadMessage[],
            },
        ],
        threadLoading: [
            false,
            {
                askMax: () => true,
                setThreadLoaded: (_, { testOnlyOverride }) => testOnlyOverride,
                cleanThread: () => false,
            },
        ],
        visibleSuggestions: [
            null as string[] | null,
            {
                setVisibleSuggestions: (_, { suggestions }) => suggestions,
            },
        ],
        traceId: [null as string | null, { setTraceId: (_, { traceId }) => traceId, cleanThread: () => null }],
    }),
    loaders({
        // TODO: Move question suggestions to `maxGlobalLogic`, which will make this logic `maxThreadLogic`
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
    listeners(({ actions, values, cache }) => ({
        [maxSettingsLogic.actionTypes.updateCoreMemorySuccess]: () => {
            actions.loadSuggestions({ refresh: 'blocking' })
        },
        [maxSettingsLogic.actionTypes.loadCoreMemorySuccess]: () => {
            actions.loadSuggestions({ refresh: 'async_except_on_cache_miss' })
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
            actions.setVisibleSuggestions(
                // We show 3 suggestions, and put the longest one last, so that the suggestions _as a whole_
                // look pleasant when the 3rd is wrapped to the next line (character count is imperfect but okay)
                allSuggestionsWithoutCurrentlyVisible.slice(0, 3).sort((a, b) => a.length - b.length)
            )
        },
        askMax: async ({ prompt, generationAttempt }, breakpoint) => {
            if (generationAttempt === 0) {
                actions.addMessage({
                    type: AssistantMessageType.Human,
                    content: prompt,
                    status: 'completed',
                })
            }

            try {
                // Generate a trace ID for the conversation run
                const traceId = uuid()
                actions.setTraceId(traceId)

                cache.generationController = new AbortController()

                const response = await api.conversations.stream(
                    {
                        content: prompt,
                        contextual_tools: Object.fromEntries(values.tools.map((tool) => [tool.name, tool.context])),
                        conversation: values.conversation?.id,
                        trace_id: traceId,
                    },
                    {
                        signal: cache.generationController.signal,
                    }
                )
                const reader = response.body?.getReader()

                if (!reader) {
                    return
                }

                const decoder = new TextDecoder()

                const parser = createParser({
                    onEvent: ({ data, event }) => {
                        if (event === AssistantEventType.Message) {
                            const parsedResponse = parseResponse<RootAssistantMessage>(data)
                            if (!parsedResponse) {
                                return
                            }

                            if (isHumanMessage(parsedResponse)) {
                                actions.replaceMessage(values.threadRaw.length - 1, {
                                    ...parsedResponse,
                                    status: 'completed',
                                })
                            } else if (isAssistantToolCallMessage(parsedResponse)) {
                                for (const [toolName, toolResult] of Object.entries(parsedResponse.ui_payload)) {
                                    values.toolMap[toolName]?.callback(toolResult)
                                }
                                actions.addMessage({
                                    ...parsedResponse,
                                    status: 'completed',
                                })
                            } else if (values.threadRaw[values.threadRaw.length - 1].status === 'completed') {
                                actions.addMessage({
                                    ...parsedResponse,
                                    status: !parsedResponse.id ? 'loading' : 'completed',
                                })
                            } else if (parsedResponse) {
                                actions.replaceMessage(values.threadRaw.length - 1, {
                                    ...parsedResponse,
                                    status: !parsedResponse.id ? 'loading' : 'completed',
                                })
                            }
                        } else if (event === AssistantEventType.Status) {
                            const parsedResponse = parseResponse<AssistantGenerationStatusEvent>(data)
                            if (!parsedResponse) {
                                return
                            }

                            if (parsedResponse.type === AssistantGenerationStatusType.GenerationError) {
                                actions.setMessageStatus(values.threadRaw.length - 1, 'error')
                            }
                        } else if (event === AssistantEventType.Conversation) {
                            const parsedResponse = parseResponse<Conversation>(data)
                            if (!parsedResponse) {
                                return
                            }
                            actions.setConversation(parsedResponse)
                        }
                    },
                })

                while (true) {
                    const { done, value } = await reader.read()
                    parser.feed(decoder.decode(value))
                    if (done) {
                        break
                    }
                }
            } catch (e) {
                // Exclude AbortController exceptions
                if (!(e instanceof DOMException) || e.name !== 'AbortError') {
                    // Prevents parallel generation attempts. Total wait time is: 21 seconds.
                    if (e instanceof ApiError && e.status === 409 && generationAttempt < 6) {
                        await breakpoint(1000 * (generationAttempt + 1))
                        actions.askMax(prompt, generationAttempt + 1)
                        return
                    }

                    const relevantErrorMessage = { ...FAILURE_MESSAGE, id: uuid() } // Generic message by default
                    if (e instanceof ApiError && e.status === 429) {
                        relevantErrorMessage.content = "You've reached my usage limit for now. Please try again later."
                    } else {
                        posthog.captureException(e) // Unhandled error, log to Sentry
                        console.error(e)
                    }

                    if (values.threadRaw[values.threadRaw.length - 1]?.status === 'loading') {
                        actions.replaceMessage(values.threadRaw.length - 1, relevantErrorMessage)
                    } else if (values.threadRaw[values.threadRaw.length - 1]?.status !== 'error') {
                        actions.addMessage(relevantErrorMessage)
                    }
                }
            }

            actions.setThreadLoaded()
            cache.generationController = undefined
        },
        stopGeneration: async () => {
            if (!values.conversation?.id) {
                return
            }

            try {
                await api.conversations.cancel(values.conversation.id)
                cache.generationController?.abort()
                actions.resetThread()
            } catch (e: any) {
                lemonToast.error(e?.data?.detail || 'Failed to cancel the generation.')
            }
        },
        retryLastMessage: () => {
            const lastMessage = values.threadRaw.filter(isHumanMessage).pop() as HumanMessage | undefined
            if (lastMessage) {
                actions.askMax(lastMessage.content)
            }
        },
        addMessage: (payload) => {
            if (isHumanMessage(payload.message) || isVisualizationMessage(payload.message)) {
                actions.scrollThreadToBottom()
            }
        },
        replaceMessage: (payload) => {
            if (isVisualizationMessage(payload.message)) {
                actions.scrollThreadToBottom()
            }
        },
        scrollThreadToBottom: () => {
            requestAnimationFrame(() => {
                // On next frame so that the message has been rendered
                const threadEl = document.getElementsByClassName('@container/thread')[0]
                let scrollableEl = threadEl?.parentElement // .Navigation3000__scene or .SidePanel3000__content
                if (scrollableEl && !scrollableEl.classList.contains('SidePanel3000__content')) {
                    // In this case we need to go up to <main>, since .Navigation3000__scene is not scrollable
                    scrollableEl = scrollableEl.parentElement
                }
                if (scrollableEl) {
                    scrollableEl.scrollTo({
                        top: threadEl.scrollHeight,
                        behavior: 'smooth',
                    })
                }
            })
        },
        startNewConversation: () => {
            if (values.conversation) {
                if (values.threadLoading) {
                    actions.stopGeneration()
                }
                actions.cleanThread()
            }
        },
    })),
    selectors({
        threadGrouped: [
            (s) => [s.threadRaw, s.threadLoading],
            (thread, threadLoading): ThreadMessage[][] => {
                const threadGrouped: ThreadMessage[][] = []
                for (let i = 0; i < thread.length; i++) {
                    const currentMessage: ThreadMessage = thread[i]
                    const previousMessage: ThreadMessage | undefined = thread[i - 1]
                    if (isHumanMessage(currentMessage) === isHumanMessage(previousMessage)) {
                        const lastThreadSoFar = threadGrouped[threadGrouped.length - 1]
                        if (currentMessage.id && previousMessage.type === AssistantMessageType.Reasoning) {
                            // Only preserve the latest reasoning message, and remove once reasoning is done
                            lastThreadSoFar[lastThreadSoFar.length - 1] = currentMessage
                        } else {
                            lastThreadSoFar.push(currentMessage)
                        }
                    } else {
                        threadGrouped.push([currentMessage])
                    }
                }
                if (threadLoading) {
                    const finalMessageSoFar = threadGrouped.at(-1)?.at(-1)
                    if (finalMessageSoFar?.type === AssistantMessageType.Human || finalMessageSoFar?.id) {
                        // If now waiting for the current node to start streaming, add "Thinking" message
                        // so that there's _some_ indication of processing
                        const thinkingMessage: ReasoningMessage & ThreadMessage = {
                            type: AssistantMessageType.Reasoning,
                            content: 'Thinking',
                            status: 'completed',
                            id: 'loader',
                        }
                        if (finalMessageSoFar.type === AssistantMessageType.Human) {
                            // If the last message was human, we need to add a new "ephemeral" AI group
                            threadGrouped.push([thinkingMessage])
                        } else {
                            // Otherwise, add to the last group
                            threadGrouped[threadGrouped.length - 1].push(thinkingMessage)
                        }
                    }
                }
                return threadGrouped
            },
        ],
        formPending: [
            (s) => [s.threadRaw],
            (threadRaw) => {
                const lastMessage = threadRaw[threadRaw.length - 1]
                if (lastMessage && isAssistantMessage(lastMessage)) {
                    return !!lastMessage.meta?.form
                }
                return false
            },
        ],
        inputDisabled: [(s) => [s.formPending], (formPending) => formPending],
        submissionDisabledReason: [
            (s) => [s.formPending, s.dataProcessingAccepted, s.question, s.threadLoading],
            (formPending, dataProcessingAccepted, question, threadLoading): string | undefined => {
                if (threadLoading) {
                    return undefined
                }

                if (!dataProcessingAccepted) {
                    return 'Please accept OpenAI processing data'
                }

                if (formPending) {
                    return 'Please choose one of the options above'
                }

                if (!question) {
                    return 'I need some input first'
                }

                return undefined
            },
        ],
    }),
    afterMount(({ actions, values }) => {
        // We only load suggestions on mount if core memory is present
        if (values.coreMemory) {
            // In this case we're fine with even really old cached values
            actions.loadSuggestions({ refresh: 'async_except_on_cache_miss' })
        }
        // If there is a prefill question from side panel state (from opening Max within the app), use it
        if (
            !values.question &&
            sidePanelStateLogic.isMounted() &&
            sidePanelStateLogic.values.selectedTab === SidePanelTab.Max &&
            sidePanelStateLogic.values.selectedTabOptions
        ) {
            actions.setQuestion(sidePanelStateLogic.values.selectedTabOptions)
        }
    }),
    permanentlyMount(), // Prevent state from being reset when Max is unmounted, especially key in the side panel
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
