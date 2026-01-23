import { createParser } from 'eventsource-parser'
import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { uuid } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import {
    AgentMode,
    AssistantEventType,
    AssistantGenerationStatusEvent,
    AssistantGenerationStatusType,
    AssistantMessage,
    AssistantMessageType,
    RootAssistantMessage,
} from '~/queries/schema/schema-assistant-messages'
import { ProductKey } from '~/queries/schema/schema-general'
import { Conversation } from '~/types'

import type { onboardingChatLogicType } from './onboardingChatLogicType'

export type MessageStatus = 'loading' | 'completed' | 'error'

export interface OnboardingChatMessage {
    id: string
    role: 'assistant' | 'user'
    content: string
    status: MessageStatus
}

// Product keywords the AI uses when recommending products
// The AI is instructed to use exact product names in bold, so we match those specifically
const PRODUCT_KEYWORDS: Record<string, ProductKey> = {
    'product analytics': ProductKey.PRODUCT_ANALYTICS,
    'session replay': ProductKey.SESSION_REPLAY,
    'session recording': ProductKey.SESSION_REPLAY,
    'session recordings': ProductKey.SESSION_REPLAY,
    'feature flags': ProductKey.FEATURE_FLAGS,
    'feature flag': ProductKey.FEATURE_FLAGS,
    experiments: ProductKey.EXPERIMENTS,
    'a/b test': ProductKey.EXPERIMENTS,
    'a/b testing': ProductKey.EXPERIMENTS,
    surveys: ProductKey.SURVEYS,
    survey: ProductKey.SURVEYS,
    'error tracking': ProductKey.ERROR_TRACKING,
    'web analytics': ProductKey.WEB_ANALYTICS,
    'website analytics': ProductKey.WEB_ANALYTICS,
    'llm observability': ProductKey.LLM_ANALYTICS,
    'data warehouse': ProductKey.DATA_WAREHOUSE,
}

// Extract product recommendations from AI message content
function extractRecommendedProducts(content: string): ProductKey[] {
    const lowerContent = content.toLowerCase()
    const products = new Set<ProductKey>()

    for (const [keyword, productKey] of Object.entries(PRODUCT_KEYWORDS)) {
        if (lowerContent.includes(keyword)) {
            products.add(productKey)
        }
    }

    return Array.from(products)
}

export const onboardingChatLogic = kea<onboardingChatLogicType>([
    path(['scenes', 'onboarding', 'onboardingChatLogic']),

    actions({
        sendMessage: (content: string) => ({ content }),
        addMessage: (message: OnboardingChatMessage) => ({ message }),
        updateMessage: (id: string, updates: Partial<OnboardingChatMessage>) => ({ id, updates }),
        setConversationId: (conversationId: string | null) => ({ conversationId }),
        setIsStreaming: (isStreaming: boolean) => ({ isStreaming }),
        setRecommendedProducts: (products: ProductKey[]) => ({ products }),
        toggleSelectedProduct: (product: ProductKey) => ({ product }),
        setError: (error: string | null) => ({ error }),
        reset: true,
    }),

    reducers({
        messages: [
            [] as OnboardingChatMessage[],
            {
                addMessage: (state: OnboardingChatMessage[], { message }: { message: OnboardingChatMessage }) => [
                    ...state,
                    message,
                ],
                updateMessage: (
                    state: OnboardingChatMessage[],
                    { id, updates }: { id: string; updates: Partial<OnboardingChatMessage> }
                ) => state.map((msg: OnboardingChatMessage) => (msg.id === id ? { ...msg, ...updates } : msg)),
                reset: () => [],
            },
        ],
        conversationId: [
            null as string | null,
            {
                setConversationId: (_: string | null, { conversationId }: { conversationId: string | null }) =>
                    conversationId,
                reset: () => null,
            },
        ],
        isStreaming: [
            false,
            {
                setIsStreaming: (_: boolean, { isStreaming }: { isStreaming: boolean }) => isStreaming,
                reset: () => false,
            },
        ],
        recommendedProducts: [
            [] as ProductKey[],
            {
                setRecommendedProducts: (_: ProductKey[], { products }: { products: ProductKey[] }) => products,
                reset: () => [],
            },
        ],
        selectedProducts: [
            [] as ProductKey[],
            {
                toggleSelectedProduct: (state: ProductKey[], { product }: { product: ProductKey }) =>
                    state.includes(product) ? state.filter((p) => p !== product) : [...state, product],
                reset: () => [],
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_: string | null, { error }: { error: string | null }) => error,
                reset: () => null,
            },
        ],
    }),

    selectors({
        hasRecommendations: [(s) => [s.recommendedProducts], (products: ProductKey[]) => products.length > 0],
    }),

    listeners(({ actions, values }) => ({
        sendMessage: async ({ content }: { content: string }) => {
            // Add user message
            const userMessageId = uuid()
            actions.addMessage({
                id: userMessageId,
                role: 'user',
                content,
                status: 'completed',
            })

            // Add placeholder assistant message
            const assistantMessageId = uuid()
            actions.addMessage({
                id: assistantMessageId,
                role: 'assistant',
                content: '',
                status: 'loading',
            })

            actions.setIsStreaming(true)
            actions.setError(null)

            try {
                const traceId = uuid()
                // Generate a new conversation ID if we don't have one yet
                const conversationId = values.conversationId || uuid()
                if (!values.conversationId) {
                    actions.setConversationId(conversationId)
                }

                const response = await api.conversations.stream({
                    content,
                    conversation: conversationId,
                    trace_id: traceId,
                    agent_mode: AgentMode.Onboarding,
                    contextual_tools: {},
                    ui_context: {},
                })

                // Check if response is ok
                if (!response.ok) {
                    const errorText = await response.text()
                    console.error('API error response:', response.status, errorText)
                    throw new Error(`API error ${response.status}: ${errorText}`)
                }

                const reader = response.body?.getReader()
                if (!reader) {
                    throw new Error('No response body')
                }

                const decoder = new TextDecoder()
                let fullContent = ''

                const parser = createParser({
                    onEvent: ({ data, event }) => {
                        try {
                            const parsed = JSON.parse(data)

                            if (event === AssistantEventType.Conversation) {
                                const conversation = parsed as Conversation
                                actions.setConversationId(conversation.id)
                            } else if (event === AssistantEventType.Message) {
                                const message = parsed as RootAssistantMessage

                                // Handle assistant messages
                                if (
                                    message.type === AssistantMessageType.Assistant ||
                                    message.type === AssistantMessageType.Reasoning
                                ) {
                                    const assistantMsg = message as AssistantMessage
                                    if (assistantMsg.content) {
                                        fullContent = assistantMsg.content
                                        actions.updateMessage(assistantMessageId, {
                                            content: fullContent,
                                            status: message.id?.startsWith('temp-') ? 'loading' : 'completed',
                                        })

                                        // Extract product recommendations from the response
                                        const products = extractRecommendedProducts(fullContent)
                                        if (products.length > 0) {
                                            actions.setRecommendedProducts(products)
                                        }
                                    }
                                } else if (message.type === AssistantMessageType.Failure) {
                                    // Handle failure messages from the backend
                                    const failureContent =
                                        message.content || "I'm having trouble connecting right now. Please try again."
                                    actions.updateMessage(assistantMessageId, {
                                        content: failureContent,
                                        status: 'error',
                                    })
                                    actions.setError(failureContent)
                                }
                            } else if (event === AssistantEventType.Status) {
                                const status = parsed as AssistantGenerationStatusEvent
                                if (status.type === AssistantGenerationStatusType.GenerationError) {
                                    actions.updateMessage(assistantMessageId, { status: 'error' })
                                    actions.setError('Failed to generate response')
                                }
                            }
                        } catch {
                            // Ignore parse errors for partial chunks
                        }
                    },
                })

                while (true) {
                    const { done, value } = await reader.read()
                    if (value) {
                        parser.feed(decoder.decode(value))
                    }
                    if (done) {
                        break
                    }
                }

                // Mark as completed if still loading
                const finalMessage = values.messages.find((m: OnboardingChatMessage) => m.id === assistantMessageId)
                if (finalMessage?.status === 'loading') {
                    actions.updateMessage(assistantMessageId, { status: 'completed' })
                }
            } catch (e) {
                console.error('Onboarding chat error:', e)

                let errorMessage = "I'm having trouble connecting right now. Please try again."

                // Show more details in development
                if (e instanceof Error) {
                    console.error('Error details:', e.message, e.stack)
                    // Check for specific error types
                    if (e.message.includes('401') || e.message.includes('403')) {
                        errorMessage = "Authentication error. Make sure you're logged in."
                    } else if (e.message.includes('404')) {
                        errorMessage =
                            "The AI service isn't available. Make sure the backend is running with AI enabled."
                    } else if (e.message.includes('500')) {
                        errorMessage = 'Server error. Check the backend logs for details.'
                    }
                }

                actions.updateMessage(assistantMessageId, {
                    content: errorMessage,
                    status: 'error',
                })
                actions.setError(e instanceof Error ? e.message : 'Unknown error')
            } finally {
                actions.setIsStreaming(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        // Send initial greeting
        actions.addMessage({
            id: uuid(),
            role: 'assistant',
            content:
                "Hi! I'm here to help you get the most out of PostHog. **Tell me about your product and what you're trying to achieve** - I'll recommend the best tools for your needs.",
            status: 'completed',
        })

        // Track that onboarding chat started
        eventUsageLogic.actions.reportAIChatOnboardingStarted('chat')
    }),
])
