import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import type { sidePanelMaxAILogicType } from './sidePanelMaxAILogicType'
import { sidePanelMaxAPI } from './sidePanelMaxAPI'

export interface ChatMessage {
    role: 'user' | 'assistant'
    content: string
    timestamp: string
    isRateLimited?: boolean
}

interface MaxResponse {
    content: string | { text: string; type: string }
    isRateLimited?: boolean
}

export const sidePanelMaxAILogic = kea<sidePanelMaxAILogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelMaxAILogic']),

    actions({
        submitMessage: (message: string) => ({ message }),
        clearChatHistory: true,
        appendAssistantMessage: (content: string) => ({ content }),
        setSearchingThinking: (isSearching: boolean) => ({ isSearching }),
        setRateLimited: (isLimited: boolean) => ({ isLimited }),
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
    }),

    loaders(({ actions, values }) => ({
        assistantResponse: [
            null as string | null,
            {
                submitMessage: async ({ message }, breakpoint) => {
                    try {
                        actions.setSearchingThinking(true)
                        if (!values.isRateLimited) {
                            actions.setRateLimited(false)
                        }
                        const response = (await sidePanelMaxAPI.sendMessage(message)) as MaxResponse
                        await breakpoint(100)

                        const content = typeof response.content === 'string' ? response.content : response.content.text

                        if (response.isRateLimited) {
                            actions.setRateLimited(true)
                        } else {
                            actions.setRateLimited(false)
                        }

                        actions.appendAssistantMessage(content)
                        setTimeout(() => actions.setSearchingThinking(false), 100)
                        return content
                    } catch (error: unknown) {
                        if (
                            error &&
                            typeof error === 'object' &&
                            'message' in error &&
                            typeof error.message === 'string' &&
                            (error.message.includes('429') || error.message.includes('rate limit'))
                        ) {
                            actions.setRateLimited(true)
                        } else {
                            actions.setRateLimited(false)
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
