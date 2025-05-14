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
    isRead: boolean
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
                    name: 'aleks@posthog.com',
                    dateCreated: '2021-01-01',
                    dateUpdated: '2021-01-01',
                    messages: [
                        {
                            id: 1,
                            content: 'Hello',
                            sender: 'user',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                            isRead: true,
                        },
                        {
                            id: 2,
                            content: 'Hi',
                            sender: 'assistant',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                            isRead: true,
                        },
                    ],
                },
                {
                    id: 2,
                    name: 'jane@posthog.com',
                    dateCreated: '2021-01-01',
                    dateUpdated: '2021-01-01',
                    messages: [
                        {
                            id: 1,
                            content: 'Hi',
                            sender: 'user',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                            isRead: true,
                        },
                        {
                            id: 2,
                            content: "What's up?",
                            sender: 'assistant',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                            isRead: true,
                        },
                        {
                            id: 3,
                            content: 'Not much',
                            sender: 'user',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                            isRead: false,
                        },
                    ],
                },
                {
                    id: 3,
                    name: 'john@posthog.com',
                    dateCreated: '2021-01-01',
                    dateUpdated: '2021-01-01',
                    messages: [
                        {
                            id: 1,
                            content: 'Hello',
                            sender: 'user',
                            dateCreated: '2021-01-01',
                            dateUpdated: '2021-01-01',
                            isRead: false,
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
                        isRead: true,
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
        setSelectedChatId: ({ selectedChatId }) => {
            if (values.chats.find((chat) => chat.id === selectedChatId)?.messages.some((message) => !message.isRead)) {
                actions.setChats(
                    values.chats.map((chat) => {
                        if (chat.id === selectedChatId) {
                            return { ...chat, messages: chat.messages.map((message) => ({ ...message, isRead: true })) }
                        }
                        return chat
                    })
                )
            }
        },
    })),
])
