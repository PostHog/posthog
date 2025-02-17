import { actions, kea, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'
import {
    ChatCompletionAssistantMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
} from 'openai/resources/chat/completions'
import posthog from 'posthog-js'

import { RecordingUniversalFilters } from '~/types'

import type { aiFilterLogicType } from './aiFilterLogicType'

export interface AiFilterLogicProps {
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    resetFilters: () => void
}

interface AiFilterResponse {
    result: 'filter' | 'question'
    data: any
}

const TIMEOUT_LIMIT = 10000

export const aiFilterLogic = kea<aiFilterLogicType>([
    path(['lib', 'components', 'AiFilter', 'aiFilterLogicType']),
    props({} as AiFilterLogicProps),
    actions({
        setMessages: (
            messages: (
                | ChatCompletionUserMessageParam
                | ChatCompletionAssistantMessageParam
                | ChatCompletionSystemMessageParam
            )[]
        ) => ({ messages }),
        setInput: (input: string) => ({ input }),
        setIsLoading: (isLoading: boolean) => ({ isLoading }),
        handleAi: (
            newMessages: (
                | ChatCompletionUserMessageParam
                | ChatCompletionAssistantMessageParam
                | ChatCompletionSystemMessageParam
            )[]
        ) => ({ newMessages }),
        handleReset: () => ({}),
        handleSend: () => ({}),
    }),
    reducers({
        messages: [
            [],
            {
                setMessages: (_, { messages }) => messages,
            },
        ],
        input: [
            '',
            {
                setInput: (_, { input }) => input,
            },
        ],
        isLoading: [
            false,
            {
                setIsLoading: (_, { isLoading }) => isLoading,
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        handleSend: () => {
            posthog.capture('ai_filter_send')
            const newMessages = [
                ...values.messages,
                {
                    role: 'user',
                    content: values.input,
                } as ChatCompletionUserMessageParam,
            ]
            actions.setMessages(newMessages)
            actions.handleAi(newMessages)
            actions.setInput('')
        },
        handleAi: async ({ newMessages }) => {
            actions.setIsLoading(true)

            try {
                const timeoutPromise = new Promise((_, reject) => {
                    setTimeout(() => reject(new Error('Request timed out')), TIMEOUT_LIMIT)
                })

                const contentPromise = api.recordings.aiFilters(newMessages as ChatCompletionUserMessageParam[])
                const content = (await Promise.race([contentPromise, timeoutPromise])) as AiFilterResponse

                if (content.hasOwnProperty('result')) {
                    if (content.result === 'filter') {
                        props.setFilters(content.data)
                        posthog.capture('ai_filter_success')
                    }

                    actions.setMessages([
                        ...newMessages,
                        {
                            role: 'assistant',
                            content: content.result === 'filter' ? JSON.stringify(content.data) : content.data.question,
                        } as ChatCompletionAssistantMessageParam,
                    ])
                }
            } catch (error) {
                actions.setMessages([
                    ...newMessages,
                    {
                        role: 'assistant',
                        content: 'Sorry, I was unable to process your request. Please try again.',
                    } as ChatCompletionAssistantMessageParam,
                ])
                posthog.capture('ai_filter_error')
            }

            actions.setIsLoading(false)
        },
        handleReset: () => {
            actions.setMessages([])
            props.resetFilters()
            posthog.capture('ai_filter_reset')
        },
    })),
])
