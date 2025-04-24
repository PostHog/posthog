import { kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { ConversationDetail } from '~/types'

import type { maxHistoryLogicType } from './maxHistoryLogicType'

export const maxHistoryLogic = kea<maxHistoryLogicType>([
    path(['scenes', 'max', 'maxHistoryLogic']),
    loaders({
        conversationHistory: [
            [] as ConversationDetail[],
            {
                loadConversationHistory: async () => {
                    const response = await api.conversations.list()
                    return response.results
                },
            },
        ],
    }),
])
