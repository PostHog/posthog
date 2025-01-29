import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { MessageStatus, ThreadMessage } from 'scenes/max/maxLogic'

import { AssistantMessageType } from '~/queries/schema'

import type { inferenceLogicType } from './inferenceLogicType'

export const inferenceLogic = kea<inferenceLogicType>([
    path(['scenes', 'inference', 'inferenceLogic']),
    actions({
        setInputText: (text: string) => ({ text }),
        addMessage: (message: ThreadMessage) => ({ message }),
        replaceMessage: (index: number, message: ThreadMessage) => ({ index, message }),
        setMessageStatus: (index: number, status: MessageStatus) => ({ index, status }),
        retryLastMessage: true,
        scrollThreadToBottom: true,
    }),
    reducers({
        inputText: [
            '',
            {
                setInputText: (_, { text }) => text,
            },
        ],
        threadRaw: [
            [] as ThreadMessage[],
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
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        submitInputText: {
            // TODO handle streaming updates like in Max
            submit: async () => {
                actions.addMessage({
                    type: AssistantMessageType.Human,
                    content: values.inputText,
                    status: 'completed',
                })
                const response = await api.inference.create({
                    model: 'deepseek-ai/DeepSeek-V3',
                    messages: [
                        {
                            role: 'user',
                            content: values.inputText,
                        },
                    ],
                })
                const responseJson = await response.json()
                actions.setInputText('')
                actions.addMessage({
                    type: AssistantMessageType.Assistant,
                    content: responseJson.choices[0].message.content,
                    status: 'completed',
                })
                return null
            },
        },
    })),
])
