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
import { subscriptions } from 'kea-subscriptions'
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
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { openNotebook } from '~/models/notebooksModel'
import {
    AgentMode,
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantMessageType,
    AssistantTool,
    AssistantUpdateEvent,
    FailureMessage,
    HumanMessage,
    RootAssistantMessage,
    SubagentUpdateEvent,
    TaskExecutionStatus,
} from '~/queries/schema/schema-assistant-messages'
import { Conversation, ConversationDetail, ConversationStatus, ConversationType } from '~/types'

import { EnhancedToolCall, getToolCallDescriptionAndWidget } from './Thread'
import { ToolRegistration } from './max-constants'
import { MaxBillingContext, MaxBillingContextSubscriptionLevel, maxBillingContextLogic } from './maxBillingContextLogic'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import type { maxThreadLogicType } from './maxThreadLogicType'
import { RENDERABLE_UI_PAYLOAD_TOOLS } from './messages/UIPayloadAnswer'
import { MAX_SLASH_COMMANDS, SlashCommand } from './slash-commands'
import {
    getAgentModeForScene,
    isAssistantMessage,
    isAssistantToolCallMessage,
    isHumanMessage,
    isNotebookUpdateMessage,
    isSubagentUpdateEvent,
    threadEndsWithMultiQuestionForm,
} from './utils'
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
    key((props) => {
        if (!props.tabId) {
            throw new Error('Max thread logic must have a tabId prop')
        }
        return `${props.conversationId}-${props.tabId}`
    }),

    path((key) => ['scenes', 'max', 'maxThreadLogic', key]),

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
            ['dataProcessingAccepted', 'toolMap', 'tools', 'availableStaticTools'],
            maxLogic({ tabId }),
            ['question', 'autoRun', 'threadLogicKey as activeThreadKey', 'activeStreamingThreads'],
            maxContextLogic,
            ['compiledContext'],
            maxBillingContextLogic,
            ['billingContext'],
            featureFlagLogic,
            ['featureFlags'],
            sceneLogic,
            ['sceneId'],
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
            maxGlobalLogic,
            ['loadConversation'],
        ],
    })),

    actions({
        // null prompt means resuming streaming or continuing previous generation
        reconnectToStream: true,
        streamConversation: (
            streamData: {
                agent_mode: AgentMode | null
                content: string | null
                conversation?: string
                contextual_tools?: Record<string, any>
                ui_context?: any
            },
            generationAttempt: number,
            addToThread: boolean = true
        ) => ({ streamData, generationAttempt, addToThread }),
        stopGeneration: true,
        completeThreadGeneration: true,
        addMessage: (message: ThreadMessage) => ({ message }),
        replaceMessage: (index: number, message: ThreadMessage) => ({ index, message }),
        setThread: (thread: ThreadMessage[]) => ({ thread }),
        setMessageStatus: (index: number, status: MessageStatus) => ({ index, status }),
        retryLastMessage: true,
        resetRetryCount: true,
        resetCancelCount: true,
        setConversation: (conversation: Conversation) => ({ conversation }),
        resetThread: true,
        finalizeStreamingMessages: true,
        setTraceId: (traceId: string) => ({ traceId }),
        selectCommand: (command: SlashCommand) => ({ command }),
        activateCommand: (command: SlashCommand) => ({ command }),
        setDeepResearchMode: (deepResearchMode: boolean) => ({ deepResearchMode }),
        setAgentMode: (agentMode: AgentMode | null) => ({ agentMode }),
        syncAgentModeFromConversation: (agentMode: AgentMode | null) => ({ agentMode }),
        setSupportOverrideEnabled: (enabled: boolean) => ({ enabled }),
        processNotebookUpdate: (notebookId: string, notebookContent: JSONContent) => ({ notebookId, notebookContent }),
        appendMessageToConversation: (message: string) => ({ message }),
        setForAnotherAgenticIteration: (value: boolean) => ({ value }),
        setToolCallUpdate: (
            update: AssistantUpdateEvent | SubagentUpdateEvent,
            toolMap: Record<string, ToolRegistration>
        ) => ({
            update,
            toolMap,
        }),
        setCancelLoading: (cancelLoading: boolean) => ({ cancelLoading }),
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
                // Remove streaming messages on failure so server state becomes source of truth
                finalizeStreamingMessages: (state) => state.filter((msg) => msg.status !== 'loading'),
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

        agentMode: [
            null as AgentMode | null,
            {
                setAgentMode: (_, { agentMode }) => agentMode,
                syncAgentModeFromConversation: (_, { agentMode }) => agentMode,
            },
        ],

        // Tracks if user manually selected agent mode after submission - if true, don't sync from conversation
        agentModeLockedByUser: [
            false,
            {
                setAgentMode: () => true,
                askMax: () => false,
            },
        ],

        // Edge case, storing the prompt when askMax is called but AIConsent hasn't been given (yet)
        pendingPrompt: [
            null as string | null,
            {
                askMax: (_, { prompt }) => prompt,
                completeThreadGeneration: () => null,
                stopGeneration: () => null,
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
                setToolCallUpdate: (
                    value,
                    {
                        update,
                        toolMap,
                    }: { update: AssistantUpdateEvent | SubagentUpdateEvent; toolMap: Record<string, ToolRegistration> }
                ) => {
                    const currentValue = value.get(update.tool_call_id) || []
                    const newMap = new Map(value)
                    let newValue: string
                    if (isSubagentUpdateEvent(update)) {
                        const [description, _] = getToolCallDescriptionAndWidget(
                            update.content as unknown as EnhancedToolCall,
                            toolMap
                        )
                        newValue = description
                    } else {
                        newValue = update.content
                    }
                    if (currentValue.includes(newValue) || newValue === '') {
                        return value
                    }
                    newMap.set(update.tool_call_id, [...currentValue, newValue])
                    return newMap
                },
            },
        ],

        cancelLoading: [
            false,
            {
                stopGeneration: () => true,
                setCancelLoading: (_, { cancelLoading }) => cancelLoading,
            },
        ],

        retryCount: [
            0,
            {
                retryLastMessage: (state) => state + 1,
                resetThread: () => 0,
                resetRetryCount: () => 0,
            },
        ],

        cancelCount: [
            0,
            {
                stopGeneration: (state) => state + 1,
                resetThread: () => 0,
                resetCancelCount: () => 0,
            },
        ],

        // Whether support agents have explicitly acknowledged they want to use an existing conversation
        supportOverrideEnabled: [
            false,
            {
                setSupportOverrideEnabled: (_, { enabled }) => enabled,
                // Reset when changing conversations
                setConversation: () => false,
            },
        ],
    })),

    listeners((logic) => ({
        streamConversation: async (
            { streamData: { agent_mode: agentMode, ...streamData }, generationAttempt, addToThread = true },
            breakpoint
        ) => {
            const { actions, values, cache, mount, props } = logic as BuiltLogic<maxThreadLogicType>
            // Set active streaming threads, so we know streaming is active
            const releaseStreamingLock = mount() // lock the logic - don't unmount before we're done streaming
            actions.incrActiveStreamingThreads()

            // Generate a new trace ID for this interaction
            const traceId = uuid()
            actions.setTraceId(traceId)

            if (generationAttempt === 0 && streamData.content && addToThread) {
                const message: ThreadMessage = {
                    type: AssistantMessageType.Human,
                    content: streamData.content,
                    status: 'completed',
                    trace_id: traceId,
                }
                actions.addMessage(message)
            }

            try {
                cache.generationController = new AbortController()

                // Ensure we have valid data for the API call
                const apiData: any = { ...streamData }
                apiData.trace_id = traceId

                if (values.billingContext && values.featureFlags[FEATURE_FLAGS.MAX_BILLING_CONTEXT]) {
                    apiData.billing_context = values.billingContext
                }

                if (values.deepResearchMode) {
                    apiData.deep_research_mode = true
                }

                if (agentMode) {
                    apiData.agent_mode = agentMode
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
                            onEventImplementation(event as string, data, { actions, values, props, agentMode })
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
                // Cancel any next iteration
                actions.setForAnotherAgenticIteration(false)

                // Retry logic
                async function retry(): Promise<void> {
                    await breakpoint(1000 * (generationAttempt + 1))
                    // Need to decrement the active streaming threads here, as we exit early.
                    actions.decrActiveStreamingThreads()
                    actions.streamConversation(
                        {
                            content: streamData.content,
                            conversation: streamData.conversation,
                            contextual_tools: streamData.contextual_tools,
                            ui_context: streamData.ui_context,
                            agent_mode: agentMode,
                        },
                        generationAttempt + 1
                    )
                }

                if (!(e instanceof DOMException) || e.name !== 'AbortError') {
                    let releaseException = true
                    // Generic message by default
                    const relevantErrorMessage = { ...FAILURE_MESSAGE, id: uuid() }
                    const offlineMessage = 'You appear to be offline. Please check your internet connection.'

                    // Network exception errors might be overwritten by the API wrapper, so we check for the generic Error type.
                    if (e instanceof Error && e.message.toLowerCase().includes('failed to fetch')) {
                        // Failed to fetch -> request failed to connect.
                        // If the conversation is in progress, we retry up to 15 times.
                        if (values.conversation?.status === ConversationStatus.InProgress) {
                            if (generationAttempt > 15) {
                                relevantErrorMessage.content = offlineMessage
                            } else {
                                await retry()
                                return
                            }
                        } else {
                            // No started conversation, show the offline message.
                            relevantErrorMessage.content = offlineMessage
                        }
                    } else if (e instanceof Error && e.message.toLowerCase() === 'network error') {
                        // Network error -> request failed in progress.
                        if (generationAttempt > 15) {
                            relevantErrorMessage.content = offlineMessage
                        } else {
                            await retry()
                            return
                        }
                    } else if (e instanceof ApiError) {
                        if (e.status === 400) {
                            // Validation exception for non-retryable errors, such as idempotency conflict
                            if (!e.data?.attr && e.data?.code === 'invalid_input') {
                                releaseException = false
                            }

                            // Validation exception for the content length
                            if (e.data?.attr === 'content') {
                                relevantErrorMessage.content =
                                    'Oops! Your message is too long. Ensure it has no more than 40000 characters.'
                            }
                        }

                        // Prevents parallel generation attempts. Total wait time is: 21 seconds.
                        if (e.status === 409 && generationAttempt <= 5) {
                            await retry()
                            return
                        }

                        if (e.status === 429) {
                            relevantErrorMessage.content = `You've reached PostHog AI's usage limit for the moment. Please try again ${e.formattedRetryAfter}.`
                        }

                        if (e.status === 402) {
                            relevantErrorMessage.content =
                                'Your organization reached its AI credit usage limit. Increase the limits in [Billing](/organization/billing), or ask an org admin to do so.'
                        }

                        if (e.status && e.status >= 500) {
                            relevantErrorMessage.content =
                                'Something is wrong with our servers. Please try again later.'
                        }
                    } else {
                        posthog.captureException(e)
                        console.error(e)
                    }

                    if (releaseException) {
                        // Remove streaming messages and reload from server (source of truth)
                        actions.finalizeStreamingMessages()
                        actions.addMessage(relevantErrorMessage)
                        if (values.conversation?.id) {
                            actions.loadConversation(values.conversation.id)
                        }
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
        setConversation: ({ conversation }) => {
            // Sync agentMode from conversation only if user hasn't manually selected a mode after submission
            if (!values.agentModeLockedByUser && conversation?.agent_mode) {
                actions.syncAgentModeFromConversation(conversation.agent_mode as AgentMode)
            }
        },
        askMax: async ({ prompt, addToThread = true, uiContext }) => {
            // Only process if this thread is the currently active one
            if (values.conversationId !== values.activeThreadKey) {
                return
            }
            if (!values.dataProcessingAccepted) {
                return // Skip - this will be re-fired by the `onApprove` on `AIConsentPopoverWrapper`
            }
            const agentMode = values.agentMode

            // Clear the question
            actions.setQuestion('')
            // For a new conversations, set the frontend conversation ID
            if (!values.conversation) {
                actions.setConversationId(values.conversationId)
            } else {
                const updatedConversation = {
                    ...values.conversation,
                    agent_mode: agentMode || values.conversation?.agent_mode,
                    status: ConversationStatus.InProgress,
                    updated_at: dayjs().toISOString(),
                }
                // Update the current status
                actions.setConversation(updatedConversation)
                // Update the global conversation cache
                actions.updateGlobalConversationCache(updatedConversation)
            }

            // Merge the compiled context with any additional ui_context (e.g., form_answers)
            const mergedUiContext = uiContext
                ? { ...values.compiledContext, ...uiContext }
                : values.compiledContext || undefined

            actions.streamConversation(
                {
                    agent_mode: agentMode,
                    content: prompt,
                    contextual_tools: Object.fromEntries(values.tools.map((tool) => [tool.identifier, tool.context])),
                    ui_context: mergedUiContext,
                    conversation: values.conversation?.id || values.conversationId,
                },
                0,
                addToThread
            )
        },
        stopGeneration: async () => {
            if (!values.conversation?.id) {
                actions.setCancelLoading(false)
                return
            }

            try {
                await api.conversations.cancel(values.conversation.id)
                cache.generationController?.abort()
                actions.resetThread()
            } catch (e: any) {
                lemonToast.error(e?.data?.detail || 'Failed to cancel the generation.')
            }

            try {
                await actions.loadConversation(values.conversation.id)
            } catch {}

            actions.setCancelLoading(false)
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
            actions.streamConversation({ conversation: id, content: null, agent_mode: values.agentMode }, 0)
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
            if (values.activeThreadKey !== values.conversationId && cache.unmount) {
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
        appendMessageToConversation: async ({ message }) => {
            const conversationId = values.conversationId
            if (!conversationId) {
                return
            }

            await api.conversations.appendMessage(conversationId, message)

            actions.addMessage({
                type: AssistantMessageType.Assistant,
                content: message,
                id: uuid(),
                status: 'completed',
            })
        },
    })),

    selectors({
        conversationId: [
            (s, p) => [s.conversation, p.conversationId],
            (conversation, propsConversationId) => conversation?.id || propsConversationId,
        ],

        isSharedThread: [
            (s) => [s.conversation, userLogic.selectors.user],
            (conversation, user): boolean => !!conversation?.user && !!user && conversation.user.uuid !== user.uuid,
        ],

        // Whether the current user is impersonating and viewing an existing conversation
        isImpersonatingExistingConversation: [
            (s) => [s.conversation, s.supportOverrideEnabled, userLogic.selectors.user],
            (conversation, supportOverrideEnabled, user): boolean => {
                // Only when user is impersonating
                if (!user?.is_impersonated) {
                    return false
                }
                // If conversation was created during impersonation (is_internal), allow typing
                if (conversation?.is_internal) {
                    return false
                }
                // Only applies to existing conversations
                if (!conversation?.title) {
                    return false
                }
                // Support agent has explicitly acknowledged they want to continue
                if (supportOverrideEnabled) {
                    return false
                }
                return true
            },
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
                    // Skip AssistantToolCallMessage that don't have a renderable UI payload
                    if (
                        currentMessage.type === AssistantMessageType.ToolCall &&
                        !Object.keys(currentMessage.ui_payload || {}).some((toolName) =>
                            RENDERABLE_UI_PAYLOAD_TOOLS.includes(toolName as AssistantTool)
                        )
                    ) {
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
                    // 2. The last message is a streaming ASSISTANT message (no ID or it starts with 'temp-') - it will show its own thinking/content
                    // Note: Human messages should always trigger thinking loader, only assistant messages can be "streaming"
                    // Note: NotebookUpdateMessages do stream, but they are not added to the thread until they have an id
                    const lastMessageIsStreamingAssistant =
                        finalMessageSoFar &&
                        isAssistantMessage(finalMessageSoFar) &&
                        (!finalMessageSoFar.id || finalMessageSoFar.id.startsWith('temp-'))
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

        multiQuestionFormPending: [
            (s) => [s.threadRaw],
            (threadRaw) => {
                return threadEndsWithMultiQuestionForm(threadRaw)
            },
        ],

        inputDisabled: [
            (s) => [
                s.formPending,
                s.multiQuestionFormPending,
                s.threadLoading,
                s.dataProcessingAccepted,
                s.isSharedThread,
                s.isImpersonatingExistingConversation,
            ],
            (
                formPending,
                multiQuestionFormPending,
                threadLoading,
                dataProcessingAccepted,
                isSharedThread,
                isImpersonatingExistingConversation
            ) =>
                // Input unavailable when:
                // - Answer must be provided using a form returned by Max only
                // - Answer must be provided using a multi-question form
                // - We are awaiting user to approve or reject external AI processing data
                // - Support agent is viewing an existing conversation without override
                isSharedThread ||
                formPending ||
                multiQuestionFormPending ||
                (threadLoading && !dataProcessingAccepted) ||
                isImpersonatingExistingConversation,
        ],

        contextDisabledReason: [
            (s) => [
                s.formPending,
                s.multiQuestionFormPending,
                s.threadLoading,
                s.activeStreamingThreads,
                s.isImpersonatingExistingConversation,
            ],
            (
                formPending,
                multiQuestionFormPending,
                threadLoading,
                activeStreamingThreads,
                isImpersonatingExistingConversation
            ): string | undefined => {
                // Allow users to cancel the generation
                if (threadLoading) {
                    return undefined
                }

                // Support agents should create new conversations instead of using existing ones
                if (isImpersonatingExistingConversation) {
                    return 'You should create new conversations during impersonation. Use the checkbox to override.'
                }

                if (formPending) {
                    return 'Please choose one of the options above'
                }

                if (multiQuestionFormPending) {
                    return 'Please answer the questions above'
                }

                // Prevent submission if too many active streaming threads (limit: 10)
                if (activeStreamingThreads >= 10) {
                    return 'You have too many chats running. Please wait for one to finish.'
                }

                return undefined
            },
        ],

        submissionDisabledReason: [
            (s) => [s.contextDisabledReason, s.question],
            (contextDisabledReason, question): string | undefined => {
                // Context-related reasons take precedence (form pending, streaming, etc.)
                if (contextDisabledReason) {
                    return contextDisabledReason
                }

                if (!question) {
                    return 'I need some input first'
                }

                return undefined
            },
        ],

        filteredCommands: [
            (s) => [s.question, s.featureFlags, s.threadLoading, s.billingContext],
            (
                question: string,
                featureFlags: Record<string, boolean | string>,
                threadLoading: boolean,
                billingContext: MaxBillingContext | null
            ): SlashCommand[] => {
                const hasPaidPlan =
                    billingContext?.subscription_level === MaxBillingContextSubscriptionLevel.PAID ||
                    billingContext?.subscription_level === MaxBillingContextSubscriptionLevel.CUSTOM ||
                    billingContext?.trial?.is_active ||
                    process.env.NODE_ENV === 'development'

                return MAX_SLASH_COMMANDS.filter(
                    (command) =>
                        command.name.toLowerCase().startsWith(question.toLowerCase()) &&
                        (!command.flag || featureFlags[command.flag]) &&
                        (!command.requiresIdle || !threadLoading) &&
                        (!command.requiresPaidPlan || hasPaidPlan)
                )
            },
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
                    ? conversation?.type !== ConversationType.DeepResearch
                    : true,
        ],
    }),

    afterMount((logic) => {
        const { actions, values, props, cache } = logic
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
        } else if (
            props.conversation?.status === ConversationStatus.InProgress &&
            !values.streamingActive &&
            !cache.generationController
        ) {
            // If the conversation is in progress and we don't have an active stream, reconnect
            setTimeout(() => {
                actions.reconnectToStream()
            }, 0)
        }
    }),

    subscriptions(({ actions, values }) => ({
        sceneId: (sceneId: Scene | null) => {
            // Only auto-set mode when no conversation is active
            if (!values.conversation) {
                const suggestedMode = getAgentModeForScene(sceneId)
                if (suggestedMode !== values.agentMode) {
                    // Use sync action to not lock - allows conversation to still update mode if agent changes it
                    actions.syncAgentModeFromConversation(suggestedMode)
                }
            }
        },
    })),
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
    return group.map((message, messageIndex) => {
        message = { ...message }
        // A message is in the final group if it comes after or is the last human message
        const isFinalGroup = messageIndex >= lastHumanMessageIndex
        if (isAssistantMessage(message) && message.tool_calls && message.tool_calls.length > 0) {
            const isLastPlanningMessage = message.id === lastPlanningMessageId
            message.tool_calls = message.tool_calls.map<EnhancedToolCall>((toolCall) => {
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
        }
        return message
    })
}

/** Assistant streaming event handler. */
export async function onEventImplementation(
    event: string,
    data: string,
    {
        actions,
        values,
        props,
        agentMode,
    }: Pick<BuiltLogic<maxThreadLogicType>, 'actions' | 'values' | 'props'> & {
        agentMode: AgentMode | null
    }
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
            agent_mode: agentMode,
        }

        actions.setConversation(conversationWithTitle)
        actions.updateGlobalConversationCache(conversationWithTitle)
    } else if (event === AssistantEventType.Update) {
        const parsedResponse = parseResponse<AssistantUpdateEvent | SubagentUpdateEvent>(data)
        if (!parsedResponse) {
            return
        }
        actions.setToolCallUpdate(parsedResponse, values.toolMap)
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
                if (values.availableStaticTools.some((tool) => tool.identifier === toolName)) {
                    continue // Static tools (mode-level) don't operate via ui_payload
                }
                await values.toolMap[toolName]?.callback?.(toolResult, props.conversationId)
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

            if (isAssistantMessage(parsedResponse) && parsedResponse.id && parsedResponse.tool_calls?.length) {
                for (const { name: toolName, args: toolResult } of parsedResponse.tool_calls) {
                    if (!values.availableStaticTools.some((tool) => tool.identifier === toolName)) {
                        continue // Non-static tools (contextual) operate via ui_payload instead
                    }
                    await values.toolMap[toolName]?.callback?.(toolResult, props.conversationId)
                }
            }
            // Check if a message with the same ID already exists
            const existingMessageIndex = parsedResponse.id
                ? values.threadRaw.findIndex((msg) => msg.id === parsedResponse.id)
                : -1

            const isLoading = !parsedResponse.id || parsedResponse.id.startsWith('temp-')
            if (existingMessageIndex >= 0) {
                // When streaming a message with an already-present ID, we simply replace it
                // (primarily when streaming in-progress messages with a temp- ID)
                actions.replaceMessage(existingMessageIndex, {
                    ...parsedResponse,
                    status: isLoading ? 'loading' : 'completed',
                })
            } else if (isLoading) {
                // When a new temp message is streamed for the first time, we append it
                actions.addMessage({
                    ...parsedResponse,
                    status: 'loading',
                })
            } else {
                // When we get the completed messages at the end of a generation,
                // we replace from the last completed message to arrive at the final state
                const lastCompletedMessageIndex = values.threadRaw.findLastIndex((msg) => msg.status === 'completed')
                actions.replaceMessage(lastCompletedMessageIndex + 1, {
                    ...parsedResponse,
                    status: 'completed',
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
