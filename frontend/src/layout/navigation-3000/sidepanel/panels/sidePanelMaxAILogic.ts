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
        retryAfter: (message: string, retryAfter: number) => ({ message, retryAfter }),
    }),

    reducers({
        retryAfter: [
            null as number | null,
            {
                retryAfter: (_, { retryAfter }) => retryAfter,
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

                        const messageContent =
                            typeof response.content === 'string' ? response.content : response.content.text

                        actions.appendAssistantMessage(messageContent)
                        setTimeout(() => actions.setSearchingThinking(false), 100)
                        return messageContent
                    } catch (error: unknown) {
                        if (
                            typeof error === 'object' &&
                            error &&
                            'status' in error &&
                            typeof error.status === 'number'
                        ) {
                            if (error.status === 429 || error.status === 429) {
                                actions.setRateLimited(true)

                                const retryPeriod = (error as any).data?.retry_after || 15
                                actions.retryAfter(message, retryPeriod)
                            } else if ([500, 524, 529].includes(error.status)) {
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

    listeners(({ actions }) => ({
        retryAfter: async ({ retryAfter, message }, breakpoint) => {
            await breakpoint(retryAfter * 1000)
            actions.setRateLimited(false)
            actions.submitMessage(message)
        },
    })),
])
