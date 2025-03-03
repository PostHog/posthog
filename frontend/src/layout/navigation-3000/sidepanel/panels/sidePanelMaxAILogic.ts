import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import type { sidePanelMaxAILogicType } from './sidePanelMaxAILogicType'
import { sidePanelMaxAPI } from './sidePanelMaxAPI'

interface RateLimit {
    limit: number
    remaining: number
    reset: string
}

interface RateLimits {
    requests: RateLimit
    input_tokens: RateLimit
    output_tokens: RateLimit
}

export interface ChatMessage {
    role: 'user' | 'assistant'
    content: string
    timestamp: string
    isRateLimited?: boolean
    isError?: boolean
    limitType?: string
}

interface MaxResponse {
    content: string | { text: string; type: string }
    rate_limits?: RateLimits
    isError?: boolean
    limit_type?: string
}

interface RetryAction {
    message: string
    retryAfter: number
    limitType?: string
}

interface RateLimitAction {
    isLimited: boolean
    limitType?: string
}

export const sidePanelMaxAILogic = kea<sidePanelMaxAILogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelMaxAILogic']),

    actions({
        submitMessage: (message: string) => ({ message }),
        clearChatHistory: true,
        appendAssistantMessage: (content: string) => ({ content }),
        setSearchingThinking: (isSearching: boolean) => ({ isSearching }),
        setRateLimited: (isLimited: boolean, limitType?: string) => ({ isLimited, limitType }),
        setServerError: (isError: boolean) => ({ isError }),
        retryAfter: (message: string, retryAfter: number, limitType?: string) => ({ message, retryAfter, limitType }),
    }),

    reducers({
        retryAttempts: [
            0,
            {
                submitMessage: () => 0,
                retryAfter: (state) => state + 1,
                setRateLimited: (state, { isLimited }) => (isLimited ? state : 0),
            },
        ],
        retryAfter: [
            null as number | null,
            {
                retryAfter: (_, { retryAfter }) => retryAfter,
            },
        ],
        rateLimitType: [
            null as string | null,
            {
                setRateLimited: (_, { limitType }: RateLimitAction) => limitType || null,
                retryAfter: (_, { limitType }: RetryAction) => limitType || null,
            },
        ],
        currentMessages: [
            [] as ChatMessage[],
            {
                submitMessage: (state, { message }) =>
                    message.trim()
                        ? [
                              ...state,
                              {
                                  role: 'user',
                                  content: message,
                                  timestamp: new Date().toISOString(),
                              },
                          ]
                        : state,
                appendAssistantMessage: (state, { content }) => [
                    ...state,
                    {
                        role: 'assistant',
                        content,
                        timestamp: new Date().toISOString(),
                        isRateLimited: content.includes('Rate limit exceeded') || content.includes('rate-limited'),
                        isError:
                            content.includes('connect to the Anthropic API') ||
                            content.includes('status.anthropic.com'),
                    },
                ],
                clearChatHistory: () => [],
            },
        ],
        isSearchingThinking: [
            false,
            {
                setSearchingThinking: (_, { isSearching }) => isSearching,
            },
        ],
        isRateLimited: [
            false,
            {
                setRateLimited: (_, { isLimited }: RateLimitAction) => isLimited,
            },
        ],
        hasServerError: [
            false,
            {
                setServerError: (_, { isError }) => isError,
            },
        ],
    }),

    loaders(({ actions, values }) => ({
        assistantResponse: [
            null as string | null,
            {
                submitMessage: async ({ message }, breakpoint) => {
                    try {
                        // Don't retry more than twice
                        if (values.retryAttempts >= 3) {
                            actions.appendAssistantMessage(
                                "😮‍💨 I'm still experiencing rate limits. Please leave me alone for a few minutes. Scroll down and hit `End chat`, then try me again after I've had a nap. 🦔"
                            )
                            actions.setSearchingThinking(false)
                            return null
                        }

                        actions.setSearchingThinking(true)
                        actions.setServerError(false)
                        if (!values.isRateLimited) {
                            actions.setRateLimited(false)
                        }
                        const response = (await sidePanelMaxAPI.sendMessage(message)) as MaxResponse
                        await breakpoint(100)

                        const messageContent =
                            typeof response.content === 'string' ? response.content : response.content.text

                        actions.appendAssistantMessage(messageContent)

                        await breakpoint(300)
                        actions.setSearchingThinking(false)

                        return messageContent
                    } catch (error: unknown) {
                        if (
                            typeof error === 'object' &&
                            error &&
                            'status' in error &&
                            typeof error.status === 'number'
                        ) {
                            if (error.status === 429) {
                                const MAX_BACKOFF = 40 // Maximum backoff in seconds to prevent gateway timeouts
                                const retryPeriod = Math.min(
                                    (error as any).data?.retry_after || MAX_BACKOFF,
                                    MAX_BACKOFF
                                )
                                const limitType = (error as any).data?.limit_type
                                actions.setRateLimited(true, limitType)
                                if (values.retryAttempts < 2) {
                                    actions.retryAfter(message, retryPeriod, limitType)
                                } else {
                                    actions.appendAssistantMessage(
                                        "I'm still experiencing rate limits. Please wait a minute or two before trying again."
                                    )
                                    actions.setSearchingThinking(false)
                                }
                                await breakpoint(100)
                            } else if ([500, 504, 524, 529].includes(error.status)) {
                                actions.setServerError(true)
                                await breakpoint(100)
                                actions.setSearchingThinking(false)
                            }
                        } else {
                            await breakpoint(100)
                            actions.setSearchingThinking(false)
                        }

                        console.error('Error sending message:', error)
                        return null
                    }
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        retryAfter: async ({ retryAfter, message }, breakpoint) => {
            await breakpoint(retryAfter * 1000)
            actions.setRateLimited(false, undefined)
            actions.submitMessage(message)
        },
    })),
])
