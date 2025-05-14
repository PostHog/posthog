import { actions, kea, listeners, path, reducers } from 'kea'

import type { chatListLogicType } from './chatListLogicType'

export type Chat = {
    id: number
    name: string
    messages: ChatMessage[]
    dateCreated: string
    dateUpdated: string
}

export type ChatMessage = {
    id: number
    content: string
    sender: 'user' | 'assistant'
    dateCreated: string
    dateUpdated: string
}

export const chatListLogic = kea<chatListLogicType>([
    path(['products', 'chat', 'frontend', 'chatListLogic']),
    actions({
        setSelectedChatId: (selectedChatId: number | null) => ({ selectedChatId }),
        setChats: (chats: Chat[]) => ({ chats }),
        sendMessage: (message: string) => ({ message }),
        setMessage: (message: string) => ({ message }),
    }),
    reducers({
        chats: [
            [
                {
                    id: 1,
                    name: 'Chat 1',
                    dateCreated: '2021-01-01',
                    dateUpdated: '2021-01-01',
                    messages: [
                        {
                            id: 1,
                            content: 'Hello',
                            sender: 'user',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                        },
                        {
                            id: 2,
                            content: 'Hi',
                            sender: 'assistant',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                        },
                    ],
                },
                {
                    id: 2,
                    name: 'Chat 2',
                    dateCreated: '2021-01-01',
                    dateUpdated: '2021-01-01',
                    messages: [
                        {
                            id: 1,
                            content: 'Hi',
                            sender: 'user',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                        },
                        {
                            id: 2,
                            content: "What's up?",
                            sender: 'assistant',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                        },
                        {
                            id: 3,
                            content: 'Not much',
                            sender: 'user',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                        },
                    ],
                },
                {
                    id: 3,
                    name: 'Chat 3',
                    dateCreated: '2021-01-01',
                    dateUpdated: '2021-01-01',
                    messages: [
                        {
                            id: 1,
                            content: 'Hello',
                            sender: 'user',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                        },
                    ],
                },
            ],
            {
                setChats: (_, { chats }) => chats,
            },
        ],
        selectedChatId: [
            null as number | null,
            {
                setSelectedChatId: (_, { selectedChatId }) => selectedChatId,
            },
        ],
        message: [
            '',
            {
                setMessage: (_, { message }) => message,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        sendMessage: ({ message }) => {
            if (values.selectedChatId) {
                const chat = values.chats.find((chat) => chat.id === values.selectedChatId)
                if (chat) {
                    const newMessage: ChatMessage = {
                        id: Date.now(),
                        content: message,
                        sender: 'assistant' as const,
                        dateCreated: new Date().toISOString(),
                        dateUpdated: new Date().toISOString(),
                    }
                    actions.setChats(
                        values.chats.map((chat) => {
                            if (chat.id === values.selectedChatId) {
                                return { ...chat, messages: [...chat.messages, newMessage] }
                            }
                            return chat
                        })
                    )
                    actions.setMessage('')
                }
            }
        },
    })),
])
