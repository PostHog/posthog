import { createParser } from 'eventsource-parser'
import {
    actions,
    afterMount,
    beforeUnmount,
    BuiltLogic,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import api, { ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { uuid } from 'lib/utils'
import posthog from 'posthog-js'

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
import { Conversation, ConversationDetail, ConversationStatus } from '~/types'

import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import type { maxThreadLogicType } from './maxThreadLogicType'
import { isAssistantMessage, isAssistantToolCallMessage, isHumanMessage, isReasoningMessage } from './utils'

export type MessageStatus = 'loading' | 'completed' | 'error'

export type ThreadMessage = RootAssistantMessage & {
    status: MessageStatus
}

const FAILURE_MESSAGE: FailureMessage & ThreadMessage = {
    type: AssistantMessageType.Failure,
    content: 'Oops! It looks like I’m having trouble answering this. Could you please try again?',
    status: 'completed',
}

export interface MaxThreadLogicProps {
    conversationId: string
    conversation?: ConversationDetail | null
}

export const maxThreadLogic = kea<maxThreadLogicType>([
    path(['scenes', 'max', 'maxThreadLogic']),

    key((props) => props.conversationId),

    props({} as MaxThreadLogicProps),

    propsChanged(({ actions, values, props }) => {
        // Streaming is active, do not update the thread
        if (!props.conversation) {
            return
        }

        // New messages have been added since we last updated the thread
        if (!values.streamingActive && props.conversation.messages.length > values.threadMessageCount) {
            actions.setThread(
                props.conversation.messages.map((message) => ({
                    ...message,
                    status: 'completed',
                }))
            )
        }

        // Check if the meta fields like the `status` field have changed
        const newConversation = removeConversationMessages(props.conversation)
        if (!values.conversation || JSON.stringify(values.conversation) !== JSON.stringify(newConversation)) {
            actions.setConversation(newConversation)
        }
    }),

    connect(() => ({
        values: [
            maxGlobalLogic,
            ['dataProcessingAccepted', 'toolMap', 'tools'],
            maxLogic,
            ['question', 'threadKeys', 'autoRun', 'conversationId as selectedConversationId', 'activeStreamingThreads'],
        ],
        actions: [
            maxLogic,
            [
                'setQuestion',
                'loadConversationHistory',
                'setThreadKey',
                'prependOrReplaceConversation as updateGlobalConversationCache',
                'setActiveStreamingThreads',
                'setConversationId',
                'setAutoRun',
            ],
        ],
    })),

    actions({
        askMax: (prompt: string, generationAttempt: number = 0) => ({ prompt, generationAttempt }),
        stopGeneration: true,
        completeThreadGeneration: true,
        addMessage: (message: ThreadMessage) => ({ message }),
        replaceMessage: (index: number, message: ThreadMessage) => ({ index, message }),
        setThread: (thread: ThreadMessage[]) => ({ thread }),
        setMessageStatus: (index: number, status: MessageStatus) => ({ index, status }),
        retryLastMessage: true,
        setConversation: (conversation: Conversation) => ({ conversation }),
        resetThread: true,
        setTraceId: (traceId: string) => ({ traceId }),
    }),

    reducers(({ props }) => ({
        conversation: [
            props.conversation ? removeConversationMessages(props.conversation) ?? null : null,
            {
                setConversation: (_, { conversation }) => conversation,
            },
        ],

        threadRaw: [
            (props.conversation?.messages ?? []) as ThreadMessage[],
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
                setThread: (_, { thread }) => thread,
            },
        ],

        // Specific case when the conversation is in progress on the backend, but the device doesn't have an open stream
        conversationLoading: [
            false,
            {
                setConversation: (_, { conversation }) =>
                    conversation && conversation.status === ConversationStatus.InProgress,
            },
        ],

        streamingActive: [
            false,
            {
                askMax: () => true,
                completeThreadGeneration: () => false,
            },
        ],

        // Trace ID is used for the conversation metrics in the UI
        traceId: [null as string | null, { setTraceId: (_, { traceId }) => traceId, cleanThread: () => null }],
    })),

    listeners(({ actions, values, cache, props }) => ({
        askMax: async ({ prompt, generationAttempt }, breakpoint) => {
            // Clear the question
            actions.setQuestion('')
            // Set active streaming threads, so we now how many are running
            actions.setActiveStreamingThreads(1)

            // For a new conversations, set the temporary conversation ID, which will be replaced with the actual conversation ID once the first message is generated
            if (!values.conversation) {
                actions.setConversationId(values.conversationId)
            } else {
                const updatedConversation = {
                    ...values.conversation,
                    status: ConversationStatus.InProgress,
                    updated_at: dayjs().toISOString(),
                }
                // Update the current status
                actions.setConversation(updatedConversation)
                // Update the global conversation cache
                actions.updateGlobalConversationCache(updatedConversation)
            }

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
                        // A Conversation object is only received when the conversation is new
                        if (event === AssistantEventType.Conversation) {
                            const parsedResponse = parseResponse<Conversation>(data)
                            if (!parsedResponse) {
                                return
                            }

                            const conversationWithTitle = {
                                ...parsedResponse,
                                title: parsedResponse.title || 'New chat',
                            }

                            // Set the mapping of conversation ID and thread ID, so we can get back to this thread later.
                            if (!values.threadKeys[props.conversationId]) {
                                actions.setThreadKey(parsedResponse.id, props.conversationId)
                            }

                            // Update the local cache
                            actions.setConversation(conversationWithTitle)
                            // Update the global conversation cache
                            actions.updateGlobalConversationCache(conversationWithTitle)
                            // Set the current conversation ID
                            actions.setConversationId(parsedResponse.id)
                        } else if (event === AssistantEventType.Message) {
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
                            } else if (
                                values.threadRaw[values.threadRaw.length - 1]?.status === 'completed' ||
                                values.threadRaw.length === 0
                            ) {
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
                    const relevantErrorMessage = { ...FAILURE_MESSAGE, id: uuid() } // Generic message by default

                    // Prevents parallel generation attempts. Total wait time is: 21 seconds.
                    if (e instanceof ApiError) {
                        if (e.status === 409 && generationAttempt < 6) {
                            await breakpoint(1000 * (generationAttempt + 1))
                            actions.askMax(prompt, generationAttempt + 1)
                            return
                        }

                        if (e.status === 429) {
                            relevantErrorMessage.content = `You've reached my usage limit for now. Please try again ${e.formattedRetryAfter}.`
                        }

                        if (e.status === 400 && e.data?.attr === 'content') {
                            relevantErrorMessage.content =
                                'Oops! Your message is too long. Ensure it has no more than 40000 characters.'
                        }
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
            actions.setActiveStreamingThreads(-1)
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

        completeThreadGeneration: () => {
            // Update the conversation history to include the new conversation
            actions.loadConversationHistory({ doNotUpdateCurrentThread: true })

            if (!values.conversation) {
                return
            }

            const newConversation = {
                ...values.conversation,
                status: ConversationStatus.Idle,
            }

            actions.setConversation(newConversation)
            actions.updateGlobalConversationCache(newConversation)

            // Must go last. Otherwise, the logic will be unmounted before the lifecycle finishes.
            if (values.selectedConversationId !== values.conversationId && cache.unmount) {
                cache.unmount()
            }
        },
    })),

    selectors({
        conversationId: [
            (s, p) => [s.conversation, p.conversationId],
            (conversation, propsConversationId) => conversation?.id || propsConversationId,
        ],

        threadLoading: [
            (s) => [s.conversationLoading, s.streamingActive],
            (conversationLoading, streamingActive) => conversationLoading || streamingActive,
        ],

        threadGrouped: [
            (s) => [s.threadRaw, s.threadLoading],
            (thread, threadLoading): ThreadMessage[][] => {
                const isHumanMessageType = (message?: ThreadMessage): boolean =>
                    message?.type === AssistantMessageType.Human
                const threadGrouped: ThreadMessage[][] = []

                for (let i = 0; i < thread.length; i++) {
                    const currentMessage: ThreadMessage = thread[i]
                    const previousMessage = thread[i - 1] as ThreadMessage | undefined

                    if (currentMessage.type === AssistantMessageType.ToolCall && !currentMessage.visible) {
                        continue
                    }

                    // Do not use the human message type guard here, as it incorrectly infers the type
                    if (previousMessage && isHumanMessageType(currentMessage) === isHumanMessageType(previousMessage)) {
                        const lastThreadSoFar = threadGrouped[threadGrouped.length - 1]
                        if (
                            currentMessage.id &&
                            previousMessage &&
                            previousMessage.type === AssistantMessageType.Reasoning
                        ) {
                            // Only preserve the latest reasoning message, and remove once reasoning is done
                            lastThreadSoFar[lastThreadSoFar.length - 1] = currentMessage
                        } else if (lastThreadSoFar) {
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

        threadMessageCount: [
            (s) => [s.threadRaw],
            (threadRaw) => threadRaw.filter((message) => !isReasoningMessage(message)).length,
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
            (s) => [s.formPending, s.dataProcessingAccepted, s.question, s.threadLoading, s.activeStreamingThreads],
            (
                formPending,
                dataProcessingAccepted,
                question,
                threadLoading,
                activeStreamingThreads
            ): string | undefined => {
                // Allow users to cancel the generation
                if (threadLoading) {
                    return undefined
                }

                if (!dataProcessingAccepted) {
                    return 'Please accept the data processing'
                }

                if (formPending) {
                    return 'Please choose one of the options above'
                }

                if (!question) {
                    return 'I need some input first'
                }

                // Prevent submission if there are active streaming threads
                if (activeStreamingThreads > 0) {
                    return 'Please wait for one of the chats to finish'
                }

                return undefined
            },
        ],
    }),

    afterMount((logic) => {
        const { actions, values, cache, mount } = logic as BuiltLogic<maxThreadLogicType>
        // Prevent unmounting of the logic until the streaming finishes.
        // Increment a counter of active logics by one and then decrement it when the logic unmounts or finishes
        cache.unmount = mount()

        if (values.autoRun && values.question) {
            actions.askMax(values.question)
            actions.setAutoRun(false)
        }
    }),

    beforeUnmount(({ cache, values }) => {
        if (!values.streamingActive) {
            cache.unmount()
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

function removeConversationMessages({ messages, ...conversation }: ConversationDetail): Conversation {
    return conversation
}
