import { createParser } from 'eventsource-parser'
import {
    BuiltLogic,
    actions,
    afterMount,
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
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils'
import { maxContextLogic } from 'scenes/max/maxContextLogic'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookTarget } from 'scenes/notebooks/types'
import { urls } from 'scenes/urls'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { openNotebook } from '~/models/notebooksModel'
import {
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantMessageType,
    AssistantUpdateEvent,
    FailureMessage,
    HumanMessage,
    RootAssistantMessage,
    TaskExecutionStatus,
} from '~/queries/schema/schema-assistant-messages'
import { Conversation, ConversationDetail, ConversationStatus, ConversationType } from '~/types'

import { maxBillingContextLogic } from './maxBillingContextLogic'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import type { maxThreadLogicType } from './maxThreadLogicType'
import { MAX_SLASH_COMMANDS, SlashCommand } from './slash-commands'
import { isAssistantMessage, isAssistantToolCallMessage, isHumanMessage, isNotebookUpdateMessage } from './utils'
import { getRandomThinkingMessage } from './utils/thinkingMessages'

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
    tabId: string // used to refer back to MaxLogic
    conversationId: string
    conversation?: ConversationDetail | null
}

export const maxThreadLogic = kea<maxThreadLogicType>([
    path(['scenes', 'max', 'maxThreadLogic']),

    key((props) => {
        if (!props.tabId) {
            throw new Error('Max thread logic must have a tabId prop')
        }
        return `${props.conversationId}-${props.tabId}`
    }),

    props({} as MaxThreadLogicProps),

    propsChanged(({ actions, values, props }) => {
        // Streaming is active, do not update the thread
        if (!props.conversation) {
            return
        }

        // New messages have been added since we last updated the thread
        if (!values.streamingActive && props.conversation.messages.length > values.threadMessageCount) {
            actions.setThread(updateMessagesWithCompletedStatus(props.conversation.messages))
        }

        // Check if the meta fields like the `status` field have changed
        const newConversation = removeConversationMessages(props.conversation)
        if (!values.conversation || JSON.stringify(values.conversation) !== JSON.stringify(newConversation)) {
            actions.setConversation(newConversation)
        }
    }),

    connect(({ tabId }: MaxThreadLogicProps) => ({
        values: [
            maxGlobalLogic,
            ['dataProcessingAccepted', 'toolMap', 'tools'],
            maxLogic({ tabId }),
            ['question', 'autoRun', 'conversationId as selectedConversationId', 'activeStreamingThreads'],
            maxContextLogic,
            ['compiledContext'],
            maxBillingContextLogic,
            ['billingContext'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            maxLogic({ tabId }),
            [
                'askMax',
                'setQuestion',
                'loadConversationHistory',
                'prependOrReplaceConversation as updateGlobalConversationCache',
                'incrActiveStreamingThreads',
                'decrActiveStreamingThreads',
                'setConversationId',
                'setAutoRun',
                'loadConversationHistorySuccess',
            ],
        ],
    })),

    actions({
        // null prompt means resuming streaming or continuing previous generation
        reconnectToStream: true,
        streamConversation: (
            streamData: {
                content: string | null
                conversation?: string
                contextual_tools?: Record<string, any>
                ui_context?: any
            },
            generationAttempt: number
        ) => ({ streamData, generationAttempt }),
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
        selectCommand: (command: SlashCommand) => ({ command }),
        activateCommand: (command: SlashCommand) => ({ command }),
        setDeepResearchMode: (deepResearchMode: boolean) => ({ deepResearchMode }),
        processNotebookUpdate: (notebookId: string, notebookContent: JSONContent) => ({ notebookId, notebookContent }),
        setForAnotherAgenticIteration: (value: boolean) => ({ value }),
        setToolCallUpdate: (update: AssistantUpdateEvent) => ({ update }),
    }),

    reducers(({ props }) => ({
        conversation: [
            props.conversation ? (removeConversationMessages(props.conversation) ?? null) : null,
            {
                setConversation: (_, { conversation }) => conversation,
            },
        ],

        threadRaw: [
            updateMessagesWithCompletedStatus(props.conversation?.messages ?? []),
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
                setThread: (_, { thread }) => thread,
            },
        ],

        // Specific case when the conversation is in progress on the backend, but the device doesn't have an open stream
        conversationLoading: [
            props.conversation?.status === ConversationStatus.InProgress,
            {
                setConversation: (_, { conversation }) =>
                    conversation && conversation.status === ConversationStatus.InProgress,
            },
        ],

        streamingActive: [
            false,
            {
                askMax: () => true,
                reconnectToStream: () => true,
                streamConversation: () => true,
                completeThreadGeneration: () => false,
            },
        ],

        // Trace ID is used for the conversation metrics in the UI
        traceId: [null as string | null, { setTraceId: (_, { traceId }) => traceId, cleanThread: () => null }],

        deepResearchMode: [
            false,
            {
                setDeepResearchMode: (_, { deepResearchMode }) => deepResearchMode,
                setConversation: (_, { conversation }) => conversation?.type === ConversationType.DeepResearch,
            },
        ],

        // Whether generation should be immediately continued due to tool execution
        isAnotherAgenticIterationScheduled: [
            false,
            {
                setForAnotherAgenticIteration: (_, { value }) => value,
                askMax: () => false,
                completeThreadGeneration: () => false,
            },
        ],

        toolCallUpdateMap: [
            new Map<string, string[]>(),
            {
                setToolCallUpdate: (value, { update }: { update: AssistantUpdateEvent }) => {
                    const currentValue = value.get(update.tool_call_id) || []
                    if (currentValue.includes(update.content) || update.content === '') {
                        return value
                    }

                    const newMap = new Map(value)
                    newMap.set(update.tool_call_id, [...currentValue, update.content])
                    return newMap
                },
            },
        ],
    })),

    listeners((logic) => ({
        streamConversation: async ({ streamData, generationAttempt }, breakpoint) => {
            const { actions, values, cache, mount, props } = logic as BuiltLogic<maxThreadLogicType>
            // Set active streaming threads, so we know streaming is active
            const releaseStreamingLock = mount() // lock the logic - don't unmount before we're done streaming
            actions.incrActiveStreamingThreads()

            if (generationAttempt === 0 && streamData.content) {
                const message: ThreadMessage = {
                    type: AssistantMessageType.Human,
                    content: streamData.content,
                    status: 'completed',
                }
                actions.addMessage(message)
            }

            try {
                cache.generationController = new AbortController()

                // Ensure we have valid data for the API call
                const apiData: any = { ...streamData }

                // Generate a new trace ID for this interaction
                const traceId = uuid()
                actions.setTraceId(traceId)
                apiData.trace_id = traceId

                if (values.billingContext && values.featureFlags[FEATURE_FLAGS.MAX_BILLING_CONTEXT]) {
                    apiData.billing_context = values.billingContext
                }

                if (values.deepResearchMode) {
                    apiData.deep_research_mode = true
                }

                const response = await api.conversations.stream(apiData, {
                    signal: cache.generationController.signal,
                })

                const reader = response.body?.getReader()
                if (!reader) {
                    return
                }

                const decoder = new TextDecoder()
                const pendingEventHandlers: Promise<void>[] = []
                const parser = createParser({
                    onEvent: async ({ data, event }) => {
                        pendingEventHandlers.push(
                            onEventImplementation(event as string, data, { actions, values, props })
                        )
                    },
                })

                while (true) {
                    const { done, value } = await reader.read()
                    parser.feed(decoder.decode(value))
                    if (done) {
                        await Promise.all(pendingEventHandlers) // Wait for all onEvent handlers to complete
                        break
                    }
                }
            } catch (e) {
                actions.setForAnotherAgenticIteration(false) // Cancel any next iteration
                if (!(e instanceof DOMException) || e.name !== 'AbortError') {
                    const relevantErrorMessage = { ...FAILURE_MESSAGE, id: uuid() } // Generic message by default

                    // Prevents parallel generation attempts. Total wait time is: 21 seconds.
                    if (e instanceof ApiError) {
                        if (e.status === 409 && generationAttempt < 6) {
                            await breakpoint(1000 * (generationAttempt + 1))
                            actions.streamConversation(
                                {
                                    content: streamData.content,
                                    conversation: streamData.conversation,
                                    contextual_tools: streamData.contextual_tools,
                                    ui_context: streamData.ui_context,
                                },
                                generationAttempt + 1
                            )
                            return
                        }

                        if (e.status === 429) {
                            relevantErrorMessage.content = `You've reached my usage limit for now. Please try again ${e.formattedRetryAfter}.`
                        }

                        if (e.status === 400 && e.data?.attr === 'content') {
                            relevantErrorMessage.content =
                                'Oops! Your message is too long. Ensure it has no more than 40000 characters.'
                        }
                    } else if (e instanceof Error && e.message.toLowerCase() === 'network error') {
                        relevantErrorMessage.content =
                            'Oops! You appear to be offline. Please check your internet connection.'
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
            actions.decrActiveStreamingThreads()
            if (values.isAnotherAgenticIterationScheduled) {
                // Continue generation after applying tool - null message in askMax "just resume generation with current context"
                actions.askMax(null)
            } else {
                // Otherwise wrap things up
                actions.completeThreadGeneration()
            }
            cache.generationController = undefined
            releaseStreamingLock() // release the lock
        },
    })),
    listeners(({ actions, values, cache }) => ({
        askMax: async ({ prompt }) => {
            if (!values.dataProcessingAccepted) {
                return // Skip - this will be re-fired by the `onApprove` on `AIConsentPopoverWrapper`
            }
            // Clear the question
            actions.setQuestion('')
            // For a new conversations, set the frontend conversation ID
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

            actions.streamConversation(
                {
                    content: prompt,
                    contextual_tools: Object.fromEntries(values.tools.map((tool) => [tool.identifier, tool.context])),
                    ui_context: values.compiledContext || undefined,
                    conversation: values.conversation?.id || values.conversationId,
                },
                0
            )
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

        reconnectToStream: () => {
            const id = values.conversationId
            if (!id) {
                return
            }
            // Only skip if this *instance* already has an open stream
            if (cache.generationController) {
                return
            }
            actions.streamConversation({ conversation: id, content: null }, 0)
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

        loadConversationHistorySuccess: ({ conversationHistory, payload }) => {
            if (payload?.doNotUpdateCurrentThread || values.autoRun || values.streamingActive) {
                return
            }
            const conversation = conversationHistory.find((c) => c.id === values.conversationId)
            if (conversation?.status === ConversationStatus.InProgress) {
                setTimeout(() => {
                    actions.reconnectToStream()
                }, 0)
            }
        },
        selectCommand: ({ command }) => {
            if (command.arg) {
                actions.setQuestion(command.name + ' ')
            } else {
                actions.setQuestion(command.name)
            }
        },
        activateCommand: ({ command }) => {
            if (command.arg) {
                actions.setQuestion(command.name + ' ') // Rest must be filled in by the user
            } else {
                actions.askMax(command.name)
            }
        },
        processNotebookUpdate: async ({ notebookId, notebookContent }) => {
            try {
                const currentPath = router.values.location.pathname
                const notebookPath = urls.notebook(notebookId)

                if (currentPath.includes(notebookPath)) {
                    // We're already on the notebook page, refresh it
                    let logic = notebookLogic.findMounted({ shortId: notebookId })
                    if (logic) {
                        logic.actions.setLocalContent(notebookContent, true, true)
                    }
                } else {
                    // Navigate to the notebook
                    await openNotebook(notebookId, NotebookTarget.Scene, undefined, (logic) => {
                        logic.actions.setLocalContent(notebookContent, true, true)
                    })
                }
            } catch (error) {
                console.error('Failed to navigate to notebook:', error)
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
            (s) => [s.threadRaw, s.threadLoading, s.toolCallUpdateMap],
            (thread, threadLoading, toolCallUpdateMap): ThreadMessage[] => {
                // Filter out messages that shouldn't be displayed
                let processedThread: ThreadMessage[] = []

                for (let i = 0; i < thread.length; i++) {
                    const currentMessage: ThreadMessage = thread[i]

                    // Skip AssistantToolCallMessage - they're now merged into AssistantMessage tool_calls
                    if (currentMessage.type === AssistantMessageType.ToolCall) {
                        continue
                    }

                    // Skip empty assistant messages with no content, tool calls, or thinking
                    if (
                        currentMessage.type === AssistantMessageType.Assistant &&
                        currentMessage.content.length === 0 &&
                        (!currentMessage.tool_calls || currentMessage.tool_calls.length === 0) &&
                        (!currentMessage.meta ||
                            !currentMessage.meta.thinking ||
                            currentMessage.meta.thinking.length === 0)
                    ) {
                        continue
                    }

                    processedThread.push(currentMessage)
                }

                // Enhance messages with tool call status
                processedThread = enhanceThreadToolCalls(processedThread, thread, threadLoading, toolCallUpdateMap)

                // Add thinking message if loading
                if (threadLoading) {
                    const finalMessageSoFar = processedThread.at(-1)

                    const thinkingMessage: AssistantMessage & ThreadMessage = {
                        type: AssistantMessageType.Assistant,
                        content: '',
                        status: 'completed',
                        id: 'loader',
                        meta: {
                            thinking: [
                                {
                                    type: 'thinking',
                                    thinking: getRandomThinkingMessage(),
                                },
                            ],
                        },
                    }

                    // Check if there are any tool calls in progress
                    const toolCallsInProgress = processedThread
                        .flatMap((message) => (isAssistantMessage(message) ? message.tool_calls : []))
                        .filter((toolCall) => toolCall && (toolCall as any).status === TaskExecutionStatus.InProgress)

                    // Don't add thinking message if:
                    // 1. There are tool calls in progress, OR
                    // 2. The last message is a streaming ASSISTANT message (no id) - it will show its own thinking/content
                    // Note: Human messages should always trigger thinking loader, only assistant messages can be "streaming"
                    // Note: NotebookUpdateMessages do stream, but they are not added to the thread until they have an id
                    const lastMessageIsStreamingAssistant =
                        finalMessageSoFar && isAssistantMessage(finalMessageSoFar) && !finalMessageSoFar.id
                    const shouldAddThinkingMessage =
                        toolCallsInProgress.length === 0 && !lastMessageIsStreamingAssistant

                    if (shouldAddThinkingMessage) {
                        // Add thinking message to indicate processing
                        processedThread.push(thinkingMessage)
                    }

                    // Special case for empty thread
                    if (processedThread.length === 0) {
                        processedThread.push(thinkingMessage)
                    }
                }

                return processedThread
            },
        ],

        threadMessageCount: [(s) => [s.threadRaw], (threadRaw) => threadRaw.length],

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

        inputDisabled: [
            (s) => [s.formPending, s.threadLoading, s.dataProcessingAccepted],
            (formPending, threadLoading, dataProcessingAccepted) =>
                // Input unavailable when:
                // - Answer must be provided using a form returned by Max only
                // - We are awaiting user to approve or reject external AI processing data
                formPending || (threadLoading && !dataProcessingAccepted),
        ],

        submissionDisabledReason: [
            (s) => [s.formPending, s.question, s.threadLoading, s.activeStreamingThreads],
            (formPending, question, threadLoading, activeStreamingThreads): string | undefined => {
                // Allow users to cancel the generation
                if (threadLoading) {
                    return undefined
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

        filteredCommands: [
            (s) => [s.question],
            (question): SlashCommand[] =>
                MAX_SLASH_COMMANDS.filter((command) => command.name.toLowerCase().startsWith(question.toLowerCase())),
        ],

        showDeepResearchModeToggle: [
            (s) => [s.conversation, s.featureFlags],
            (conversation, featureFlags) =>
                // if a conversation is already marked as deep research, or has already started (has title/is in progress), don't show the toggle
                !!featureFlags[FEATURE_FLAGS.MAX_DEEP_RESEARCH] &&
                conversation?.type !== ConversationType.DeepResearch &&
                !conversation?.title &&
                conversation?.status !== ConversationStatus.InProgress,
        ],

        showContextUI: [
            (s) => [s.conversation, s.featureFlags],
            (conversation, featureFlags) =>
                featureFlags[FEATURE_FLAGS.MAX_DEEP_RESEARCH]
                    ? conversation?.type !== ConversationType.DeepResearch &&
                      conversation?.status !== ConversationStatus.InProgress
                    : true,
        ],
    }),

    afterMount((logic) => {
        const { actions, values, props } = logic
        for (const l of maxThreadLogic.findAllMounted()) {
            if (l !== logic && l.props.conversationId === props.conversationId) {
                // We found a logic with the same conversationId, but a different tabId
                if (l.values.conversation) {
                    actions.setConversation(l.values.conversation)
                }
                if (l.values.threadRaw) {
                    actions.setThread(l.values.threadRaw)
                }
                break
            }
        }

        if (values.autoRun && values.question) {
            actions.askMax(values.question)
            actions.setAutoRun(false)
        }
    }),
])

/**
 * Enhances AssistantMessages with tool call completion status by matching
 * AssistantToolCallMessage.tool_call_id with AssistantMessage.tool_calls[].id
 * Also marks the last AssistantMessage with planning (todo_write tool calls)
 */
function enhanceThreadToolCalls(
    group: ThreadMessage[],
    fullThread: ThreadMessage[],
    isLoading: boolean,
    toolCallUpdateMap: Map<string, string[]>
): ThreadMessage[] {
    // Create a map of tool_call_id -> AssistantToolCallMessage for quick lookup
    // Search in the full thread to find ToolCall messages (which are filtered from groups)
    const toolCallCompletions = new Map<string, ThreadMessage>()

    for (const message of fullThread) {
        // Use simple type check instead of isAssistantToolCallMessage, which requires ui_payload
        // This allows us to match tool call completions in stories/tests without ui_payload
        if (message.type === AssistantMessageType.ToolCall && 'tool_call_id' in message) {
            toolCallCompletions.set((message as any).tool_call_id, message)
        }
    }

    // Find the last human message to determine the final group
    let lastHumanMessageIndex = -1
    for (let i = group.length - 1; i >= 0; i--) {
        if (isHumanMessage(group[i])) {
            lastHumanMessageIndex = i
            break
        }
    }

    // Find the last AssistantMessage that has todo_write tool calls (planning)
    let lastPlanningMessageId: string | undefined
    for (let i = group.length - 1; i >= 0; i--) {
        const message = group[i]
        if (
            isAssistantMessage(message) &&
            message.tool_calls &&
            message.tool_calls.some((tc) => tc.name === 'todo_write')
        ) {
            lastPlanningMessageId = message.id
            break
        }
    }

    // Enhance assistant messages with tool call status
    return group.map((message, index) => {
        if (isAssistantMessage(message) && message.tool_calls && message.tool_calls.length > 0) {
            // A message is in the final group if it comes after or is the last human message
            const isFinalGroup = index >= lastHumanMessageIndex
            const isLastPlanningMessage = message.id === lastPlanningMessageId
            const enhancedToolCalls = message.tool_calls.map((toolCall) => {
                const isCompleted = !!toolCallCompletions.get(toolCall.id)
                const isFailed = !isCompleted && (!isFinalGroup || !isLoading)
                return {
                    ...toolCall,
                    status: isFailed
                        ? TaskExecutionStatus.Failed
                        : isCompleted
                          ? TaskExecutionStatus.Completed
                          : TaskExecutionStatus.InProgress,
                    isLastPlanningMessage: toolCall.name === 'todo_write' && isLastPlanningMessage,
                    updates: toolCallUpdateMap.get(toolCall.id) ?? [],
                }
            })

            return {
                ...message,
                tool_calls: enhancedToolCalls,
            }
        }
        return message
    })
}

/** Assistant streaming event handler. */
async function onEventImplementation(
    event: string,
    data: string,
    { actions, values, props }: Pick<BuiltLogic<maxThreadLogicType>, 'actions' | 'values' | 'props'>
): Promise<void> {
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

        actions.setConversation(conversationWithTitle)
        actions.updateGlobalConversationCache(conversationWithTitle)
    } else if (event === AssistantEventType.Update) {
        const parsedResponse = parseResponse<AssistantUpdateEvent>(data)
        if (!parsedResponse) {
            return
        }
        actions.setToolCallUpdate(parsedResponse)
        return
    } else if (event === AssistantEventType.Message) {
        const parsedResponse = parseResponse<RootAssistantMessage>(data)
        if (!parsedResponse) {
            return
        }
        if (isHumanMessage(parsedResponse)) {
            // Find the most recent Human message (the provisional bubble we added on ask)
            const lastHumanIndex = [...values.threadRaw]
                .map((m, i) => [m, i] as const)
                .reverse()
                .find(([m]) => isHumanMessage(m))?.[1]

            if (lastHumanIndex != null) {
                actions.replaceMessage(lastHumanIndex, { ...parsedResponse, status: 'completed' })
            } else {
                // Fallback – if we somehow don't have a provisional Human message, just add it
                actions.addMessage({ ...parsedResponse, status: 'completed' })
            }
        } else if (isAssistantToolCallMessage(parsedResponse)) {
            for (const [toolName, toolResult] of Object.entries(parsedResponse.ui_payload)) {
                await values.toolMap[toolName]?.callback?.(toolResult, props.conversationId)
                // The `navigate` tool is the only one doing client-side formatting currently
                if (toolName === 'navigate') {
                    parsedResponse.content = parsedResponse.content.replace(
                        toolResult.page_key,
                        breadcrumbsLogic.values.sceneBreadcrumbsDisplayString
                    )
                    actions.setForAnotherAgenticIteration(true) // Let's iterate after applying the navigate tool
                }
            }
            actions.addMessage({
                ...parsedResponse,
                status: 'completed',
            })
        } else {
            if (isNotebookUpdateMessage(parsedResponse)) {
                actions.processNotebookUpdate(parsedResponse.notebook_id, parsedResponse.content)
                if (!parsedResponse.id) {
                    // we do not want to show partial notebook update messages
                    return
                }
            }
            // Check if a message with the same ID already exists
            const existingMessageIndex = parsedResponse.id
                ? values.threadRaw.findIndex((msg) => msg.id === parsedResponse.id)
                : -1

            if (existingMessageIndex >= 0) {
                // Replace existing message with same ID
                actions.replaceMessage(existingMessageIndex, {
                    ...parsedResponse,
                    status: !parsedResponse.id ? 'loading' : 'completed',
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
}

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

/**
 * Update the status of the messages to completed, so the UI displays additional actions.
 */
function updateMessagesWithCompletedStatus(thread: RootAssistantMessage[]): ThreadMessage[] {
    return thread.map((message) => ({
        ...message,
        status: 'completed',
    }))
}
