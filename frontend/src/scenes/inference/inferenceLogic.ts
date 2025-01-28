import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import type { inferenceLogicType } from './inferenceLogicType'

export const inferenceLogic = kea<inferenceLogicType>([
    path(['scenes', 'inference', 'inferenceLogic']),
    actions({
        setInputText: (text: string) => ({ text }),
    }),
    reducers({
        inputText: [
            '',
            {
                setInputText: (_, { text }) => text,
            },
        ],
    }),
    loaders(({ values, actions }) => ({
        submitInputText: {
            // TODO handle streaming updates like in Max
            submit: async () => {
                await api.inference.create({
                    model: 'deepseek-ai/DeepSeek-V3',
                    messages: [
                        {
                            role: 'user',
                            content: values.inputText,
                        },
                    ],
                })
                actions.setInputText('')
            },
        },
    })),
])
