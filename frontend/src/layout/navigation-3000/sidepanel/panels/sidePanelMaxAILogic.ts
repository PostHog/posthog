import { actions, kea, path, reducers } from 'kea'
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
}

interface MaxResponse {
    content: string | { text: string; type: string }
    rate_limits?: RateLimits
    isError?: boolean
}

export const sidePanelMaxAILogic = kea<sidePanelMaxAILogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelMaxAILogic']),

    actions({
        submitMessage: (message: string) => ({ message }),
        clearChatHistory: true,
        appendAssistantMessage: (content: string) => ({ content }),
        setSearchingThinking: (isSearching: boolean) => ({ isSearching }),
        setRateLimited: (isLimited: boolean) => ({ isLimited }),
        setServerError: (isError: boolean) => ({ isError }),
    }),

    reducers({
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
                setRateLimited: (_, { isLimited }) => isLimited,
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
                        actions.setSearchingThinking(true)
                        actions.setServerError(false)
                        if (!values.isRateLimited) {
                            actions.setRateLimited(false)
                        }
                        const response = (await sidePanelMaxAPI.sendMessage(message)) as MaxResponse
                        await breakpoint(100)

                        let messageContent =
                            typeof response.content === 'string' ? response.content : response.content.text

                        // Check rate limits
                        const { rate_limits } = response
                        if (rate_limits) {
                            const isLimited = Object.values(rate_limits).some((limit) => limit.remaining === 0)
                            if (isLimited) {
                                actions.setRateLimited(true)
                                // Find the shortest reset time
                                const resetTimes = Object.values(rate_limits)
                                    .map((limit) => new Date(limit.reset).getTime())
                                    .filter((time) => !isNaN(time))
                                if (resetTimes.length > 0) {
                                    const earliestReset = Math.min(...resetTimes)
                                    const waitSeconds = Math.max(0, Math.ceil((earliestReset - Date.now()) / 1000))
                                    messageContent = `🫣 Rate limit hit! Please try again in ${waitSeconds} seconds. 🦔`
                                }
                            }
                        }

                        if (response.isError) {
                            actions.setServerError(true)
                        } else {
                            actions.setRateLimited(false)
                            actions.setServerError(false)
                        }

                        actions.appendAssistantMessage(messageContent)
                        setTimeout(() => actions.setSearchingThinking(false), 100)
                        return messageContent
                    } catch (error: unknown) {
                        if (
                            error &&
                            typeof error === 'object' &&
                            'message' in error &&
                            typeof error.message === 'string'
                        ) {
                            if (error.message.includes('429') || error.message.includes('rate limit')) {
                                actions.setRateLimited(true)
                            } else if (
                                error.message.includes('500') ||
                                error.message.includes('524') ||
                                error.message.includes('529')
                            ) {
                                actions.setServerError(true)
                            }
                        }
                        setTimeout(() => actions.setSearchingThinking(false), 100)
                        console.error('Error sending message:', error)
                        return null
                    }
                },
            },
        ],
    })),
])
