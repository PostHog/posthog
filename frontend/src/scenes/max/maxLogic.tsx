import { shuffle } from 'd3'
import { createParser } from 'eventsource-parser'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, decodeParams, router, urlToAction } from 'kea-router'
import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual, uuid } from 'lib/utils'
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
import { Conversation, ConversationDetail, ConversationStatus, SidePanelTab } from '~/types'

import { maxGlobalLogic } from './maxGlobalLogic'
import type { maxLogicType } from './maxLogicType'
import {
    isAssistantMessage,
    isAssistantToolCallMessage,
    isHumanMessage,
    isReasoningMessage,
    isVisualizationMessage,
} from './utils'

export type MessageStatus = 'loading' | 'completed' | 'error'

export type ThreadMessage = RootAssistantMessage & {
    status: MessageStatus
}

const FAILURE_MESSAGE: FailureMessage & ThreadMessage = {
    type: AssistantMessageType.Failure,
    content: 'Oops! It looks like I’m having trouble answering this. Could you please try again?',
    status: 'completed',
}

const HEADLINES = [
    'How can I help you build?',
    'What are you curious about?',
    'How can I help you understand users?',
    'What do you want to know today?',
]

export const maxLogic = kea<maxLogicType>([
    path(['scenes', 'max', 'maxLogic']),

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
        completeThreadGeneration: (testOnlyOverride = false) => ({ testOnlyOverride }),
        setThreadLoading: (isLoading: boolean) => ({ isLoading }),
        addMessage: (message: ThreadMessage) => ({ message }),
        replaceMessage: (index: number, message: ThreadMessage) => ({ index, message }),
        setThread: (thread: ThreadMessage[]) => ({ thread }),
        setMessageStatus: (index: number, status: MessageStatus) => ({ index, status }),
        setQuestion: (question: string) => ({ question }),
        setVisibleSuggestions: (suggestions: string[]) => ({ suggestions }),
        shuffleVisibleSuggestions: true,
        retryLastMessage: true,
        scrollThreadToBottom: (behavior?: 'instant' | 'smooth') => ({ behavior }),
        setConversationId: (conversationId: string) => ({ conversationId }),
        setConversation: (conversation: Conversation) => ({ conversation }),
        setTraceId: (traceId: string) => ({ traceId }),
        resetThread: true,
        cleanThread: true,
        startNewConversation: true,
        toggleConversationHistory: (visible?: boolean) => ({ visible }),
        loadThread: (conversation: ConversationDetail) => ({ conversation }),
        pollConversation: (currentRecursionDepth: number = 0) => ({ currentRecursionDepth }),
        goBack: true,
        setBackScreen: (screen: 'history') => ({ screen }),
        focusInput: true,
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

        conversationId: [
            null as string | null,
            {
                setConversationId: (_, { conversationId }) => conversationId,
                cleanThread: () => null,
                setConversation: (_, { conversation }) => conversation.id,
            },
        ],

        conversation: [
            null as Conversation | null,
            {
                setConversation: (_, { conversation }) => conversation,
                cleanThread: () => null,
                completeThreadGeneration: (conversation) => {
                    if (!conversation) {
                        return conversation
                    }

                    return {
                        ...conversation,
                        status: ConversationStatus.Idle,
                    }
                },
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
                setThread: (_, { thread }) => thread,
            },
        ],

        threadLoading: [
            false,
            {
                askMax: () => true,
                completeThreadGeneration: (_, { testOnlyOverride }) => testOnlyOverride,
                cleanThread: () => false,
                setThreadLoading: (_, { isLoading }) => isLoading,
            },
        ],

        visibleSuggestions: [
            null as string[] | null,
            {
                setVisibleSuggestions: (_, { suggestions }) => suggestions,
            },
        ],

        traceId: [null as string | null, { setTraceId: (_, { traceId }) => traceId, cleanThread: () => null }],

        conversationHistoryVisible: [
            false,
            {
                toggleConversationHistory: (state, { visible }) => visible ?? !state,
                startNewConversation: () => false,
            },
        ],

        backToScreen: [
            null as 'history' | null,
            {
                setBackScreen: (_, { screen }) => screen,
                startNewConversation: () => null,
            },
        ],

        /**
         * When the focus counter updates, the input component will rerender and refocus the input.
         */
        focusCounter: [0, { focusInput: (state) => state + 1 }],
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

        conversationHistory: [
            [] as ConversationDetail[],
            {
                loadConversationHistory: async (
                    // eslint-disable-next-line @typescript-eslint/no-unused-vars -- Used for conversation restoration
                    _?: {
                        /** If true, the current thread will not be updated with the retrieved conversation. */
                        doNotUpdateCurrentThread: boolean
                    }
                ) => {
                    const response = await api.conversations.list()
                    return response.results
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
                                if (parsedResponse.visible) {
                                    actions.addMessage({
                                        ...parsedResponse,
                                        status: 'completed',
                                    })
                                }
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
                        posthog.captureException(e)
                        console.error(e)
                    }

                    if (values.threadRaw[values.threadRaw.length - 1]?.status === 'loading') {
                        actions.replaceMessage(values.threadRaw.length - 1, relevantErrorMessage)
                    } else if (values.threadRaw[values.threadRaw.length - 1]?.status !== 'error') {
                        actions.addMessage(relevantErrorMessage)
                    }
                }
            }

            actions.completeThreadGeneration()
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

        scrollThreadToBottom: ({ behavior }) => {
            requestAnimationFrame(() => {
                // On next frame so that the message has been rendered
                const threadEl = document.getElementsByClassName('@container/thread')[0]
                const scrollableEl = getScrollableContainer(threadEl)
                if (scrollableEl) {
                    scrollableEl.scrollTo({
                        top: threadEl.scrollHeight,
                        behavior: (behavior ?? 'smooth') as ScrollBehavior,
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

        completeThreadGeneration: () => {
            // Update the conversation history to include the new conversation
            actions.loadConversationHistory({ doNotUpdateCurrentThread: true })
        },

        loadConversationHistorySuccess: ({ conversationHistory, payload }) => {
            if (!values.conversationId) {
                return
            }

            const conversation = conversationHistory.find((c) => c.id === values.conversationId)

            if (payload?.doNotUpdateCurrentThread) {
                // Update conversation title
                if (conversation) {
                    actions.setConversation(conversation)
                }

                return
            }

            // If the user has opened a conversation from a direct link, we verify that the conversation exists
            // after the history has been loaded.
            if (conversation) {
                actions.loadThread(conversation)
            } else {
                // If the conversation is not found, clean the thread so that the UI is consistent
                actions.cleanThread()
                lemonToast.error('Conversation has not been found.')
            }
        },

        loadConversationHistoryFailure: ({ errorObject }) => {
            lemonToast.error(errorObject?.data?.detail || 'Failed to load conversation history.')
        },

        /**
         * Loads a conversation from the history into the thread.
         */
        loadThread: ({ conversation: { messages, ...conversation } }) => {
            actions.setConversation(conversation)
            actions.setThread(messages.map((message) => ({ ...message, status: 'completed' })))

            if (conversation.status === ConversationStatus.Idle) {
                actions.setThreadLoading(false)
                actions.scrollThreadToBottom('instant')
            } else {
                // If the conversation is not idle, we need to show a loader and poll the conversation status.
                actions.setThreadLoading(true)
                actions.pollConversation()
            }
        },

        /**
         * Polls the conversation status until it's idle or reaches a max recursion depth.
         */
        pollConversation: async ({ currentRecursionDepth }, breakpoint) => {
            if (!values.conversation?.id || currentRecursionDepth > 10) {
                return
            }

            await breakpoint(2500)
            let conversation: ConversationDetail | null = null

            try {
                conversation = await api.conversations.get(values.conversation.id)
            } catch (err: any) {
                lemonToast.error(err?.data?.detail || 'Failed to load conversation.')
            }

            if (conversation && conversation.status === ConversationStatus.Idle) {
                actions.loadThread(conversation)
            } else {
                actions.pollConversation(currentRecursionDepth + 1)
            }
        },

        toggleConversationHistory: () => {
            if (values.conversationHistoryVisible) {
                const threadEl = document.getElementsByClassName('@container/thread')[0]
                const scrollableEl = getScrollableContainer(threadEl)
                if (scrollableEl) {
                    scrollableEl.scrollTo({
                        top: 0,
                        behavior: 'instant' as ScrollBehavior,
                    })
                }
            } else {
                actions.scrollThreadToBottom('instant')
            }
        },

        goBack: () => {
            if (values.backToScreen === 'history' && !values.conversationHistoryVisible) {
                actions.toggleConversationHistory(true)
            } else {
                actions.startNewConversation()
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
                    if (currentMessage.type === AssistantMessageType.ToolCall && !currentMessage.visible) {
                        continue
                    }
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
                    const thinkingMessage: ReasoningMessage & ThreadMessage = {
                        type: AssistantMessageType.Reasoning,
                        content: 'Thinking',
                        status: 'completed',
                        id: 'loader',
                    }

                    if (finalMessageSoFar?.type === AssistantMessageType.Human || finalMessageSoFar?.id) {
                        // If now waiting for the current node to start streaming, add "Thinking" message
                        // so that there's _some_ indication of processing
                        if (finalMessageSoFar.type === AssistantMessageType.Human) {
                            // If the last message was human, we need to add a new "ephemeral" AI group
                            threadGrouped.push([thinkingMessage])
                        } else {
                            // Otherwise, add to the last group
                            threadGrouped[threadGrouped.length - 1].push(thinkingMessage)
                        }
                    }

                    // Special case for the thread in progress
                    if (threadGrouped.length === 0) {
                        threadGrouped.push([thinkingMessage])
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

        toolHeadlines: [(s) => [s.tools], (tools) => tools.map((tool) => tool.introOverride?.headline).filter(Boolean)],

        toolDescriptions: [
            (s) => [s.tools],
            (tools) => tools.map((tool) => tool.introOverride?.description).filter(Boolean),
        ],

        headline: [
            (s) => [s.conversation, s.toolHeadlines],
            (conversation, toolHeadlines) => {
                if (process.env.STORYBOOK) {
                    return HEADLINES[0] // Preventing UI snapshots from being different every time
                }

                return toolHeadlines.length > 0
                    ? toolHeadlines[0]
                    : HEADLINES[
                          parseInt((conversation?.id || uuid()).split('-').at(-1) as string, 16) % HEADLINES.length
                      ]
            },
            // It's important we use a deep equality check for inputs, because we want to avoid needless re-renders
            { equalityCheck: objectsEqual },
        ],

        description: [
            (s) => [s.toolDescriptions],
            (toolDescriptions): string => {
                return `I'm Max, here to help you build a successful product. ${
                    toolDescriptions.length > 0 ? toolDescriptions[0] : 'Ask me about your product and your users.'
                }`
            },
            // It's important we use a deep equality check for inputs, because we want to avoid needless re-renders
            { equalityCheck: objectsEqual },
        ],

        conversationLoading: [
            (s) => [
                s.conversationHistory,
                s.conversationHistoryLoading,
                s.conversationId,
                s.conversation,
                s.threadLoading,
            ],
            (conversationHistory, conversationHistoryLoading, conversationId, conversation) => {
                return !conversationHistory.length && conversationHistoryLoading && conversationId && !conversation
            },
        ],

        chatTitle: [
            (s) => [s.conversationId, s.conversation, s.conversationHistoryVisible],
            (conversationId, conversation, conversationHistoryVisible) => {
                if (conversationHistoryVisible) {
                    return 'Chat history'
                }

                // Existing conversation
                if (conversation) {
                    return conversation.title ?? 'New chat'
                }

                // Conversation is loading
                if (conversationId) {
                    return null
                }

                return 'Max'
            },
        ],

        threadVisible: [
            (s) => [s.threadGrouped, s.conversationId],
            (threadGrouped, conversationId) => {
                return !!(threadGrouped.length > 0 || conversationId)
            },
        ],

        backButtonDisabled: [
            (s) => [s.threadVisible, s.conversationHistoryVisible],
            (threadVisible, conversationHistoryVisible) => {
                return !threadVisible && !conversationHistoryVisible
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
            const cleanedQuestion = sidePanelStateLogic.values.selectedTabOptions.replace(/^!/, '')
            if (sidePanelStateLogic.values.selectedTabOptions.startsWith('!')) {
                actions.askMax(cleanedQuestion)
            } else {
                actions.setQuestion(cleanedQuestion)
            }
        }
        // Load conversation history on mount
        actions.loadConversationHistory()
    }),

    urlToAction(({ actions, values }) => ({
        /**
         * When the URL contains a conversation ID, we want to make that conversation the active one.
         */
        '*': (_, search) => {
            if (!search.chat || search.chat === values.conversationId) {
                return
            }

            if (!sidePanelStateLogic.values.sidePanelOpen && !router.values.location.pathname.includes('/max')) {
                sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max)
            }

            const conversation = values.conversationHistory.find((c) => c.id === search.chat)

            if (conversation) {
                actions.loadThread(conversation)
                actions.scrollThreadToBottom('instant')
            } else if (values.conversationHistoryLoading) {
                // Conversation hasn't been loaded yet, so we handle it in `loadConversationHistory`
                actions.setConversationId(search.chat)
            }

            if (values.conversationHistoryVisible) {
                actions.toggleConversationHistory(false)
                actions.setBackScreen('history')
            }
        },
    })),

    actionToUrl(() => ({
        cleanThread: () => {
            const { chat, ...params } = decodeParams(router.values.location.search, '?')
            return [router.values.location.pathname, params, router.values.location.hash]
        },
    })),

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

function getScrollableContainer(element?: Element | null): HTMLElement | null {
    if (!element) {
        return null
    }

    const scrollableEl = element.parentElement // .Navigation3000__scene or .SidePanel3000__content
    if (scrollableEl && !scrollableEl.classList.contains('SidePanel3000__content')) {
        // In this case we need to go up to <main>, since .Navigation3000__scene is not scrollable
        return scrollableEl.parentElement
    }
    return scrollableEl
}
