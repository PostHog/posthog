import { actions, kea, listeners, path, props, reducers } from 'kea'
import api from 'lib/api'
import {
    ChatCompletionAssistantMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
} from 'openai/resources/chat/completions'

import { RecordingUniversalFilters } from '~/types'

import type { aiFilterLogicType } from './aiFilterLogicType'

export interface AiFilterLogicProps {
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    resetFilters: () => void
}

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

            const content = await api.recordings.aiFilters(newMessages as ChatCompletionUserMessageParam[])

            if (content.hasOwnProperty('result') && content.result === 'filter') {
                props.setFilters(content.data)
            }
            if (content.hasOwnProperty('result') && content.result === 'question') {
                actions.setMessages([
                    ...newMessages,
                    {
                        role: 'assistant',
                        content: content.data.question ?? '',
                    } as ChatCompletionAssistantMessageParam,
                ])
            }

            actions.setIsLoading(false)
        },
        handleReset: () => {
            actions.setMessages([])
            props.resetFilters()
        },
    })),
])
