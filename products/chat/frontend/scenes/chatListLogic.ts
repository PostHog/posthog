import { actions, kea, listeners, path, reducers } from 'kea'

import type { chatListLogicType } from './chatListLogicType'

export type Chat = {
    id: string
    person: string // email or user id, for dummy data
    team: string // team id, for dummy data
    title?: string | null
    created_at: string
    updated_at: string
    source_url?: string | null
    unread_count: number
    messages: ChatMessage[]
}

export type ChatMessage = {
    id: string
    conversation: string // chat id (UUID)
    content: string
    created_at: string
    read: boolean
    is_assistant: boolean
}

export const chatListLogic = kea<chatListLogicType>([
    path(['products', 'chat', 'frontend', 'chatListLogic']),
    actions({
        setSelectedChatId: (selectedChatId: string | null) => ({ selectedChatId }),
        setChats: (chats: Chat[]) => ({ chats }),
        sendMessage: (message: string) => ({ message }),
        setMessage: (message: string) => ({ message }),
    }),
    reducers({
        chats: [
            [
                {
                    id: '1',
                    person: 'aleks@posthog.com',
                    team: 'team1',
                    title: 'Chat with Aleks',
                    created_at: '2021-01-01T00:00:00Z',
                    updated_at: '2021-01-01T00:00:00Z',
                    source_url: null,
                    unread_count: 0,
                    messages: [
                        {
                            id: 'm1',
                            conversation: '1',
                            content: 'Hello',
                            created_at: '2021-01-01T00:00:00Z',
                            read: true,
                            is_assistant: false,
                        },
                        {
                            id: 'm2',
                            conversation: '1',
                            content: 'Hi',
                            created_at: '2021-01-01T00:01:00Z',
                            read: true,
                            is_assistant: true,
                        },
                    ],
                },
                {
                    id: '2',
                    person: 'jane@posthog.com',
                    team: 'team1',
                    title: 'Chat with Jane',
                    created_at: '2021-01-01T00:00:00Z',
                    updated_at: '2021-01-01T00:00:00Z',
                    source_url: null,
                    unread_count: 1,
                    messages: [
                        {
                            id: 'm3',
                            conversation: '2',
                            content: 'Hi',
                            created_at: '2021-01-01T00:00:00Z',
                            read: true,
                            is_assistant: true,
                        },
                        {
                            id: 'm4',
                            conversation: '2',
                            content: "What's up?",
                            created_at: '2021-01-01T00:01:00Z',
                            read: true,
                            is_assistant: true,
                        },
                        {
                            id: 'm5',
                            conversation: '2',
                            content: 'Not much',
                            created_at: '2021-01-01T00:02:00Z',
                            read: false,
                            is_assistant: false,
                        },
                    ],
                },
                {
                    id: '3',
                    person: 'john@posthog.com',
                    team: 'team1',
                    title: 'Chat with John',
                    created_at: '2021-01-01T00:00:00Z',
                    updated_at: '2021-01-01T00:00:00Z',
                    source_url: null,
                    unread_count: 1,
                    messages: [
                        {
                            id: 'm6',
                            conversation: '3',
                            content: 'Hello',
                            created_at: '2021-01-01T00:00:00Z',
                            read: false,
                            is_assistant: false,
                        },
                    ],
                },
            ],
            {
                setChats: (_, { chats }) => chats,
            },
        ],
        selectedChatId: [
            null as string | null,
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
                        id: Date.now().toString(),
                        conversation: chat.id.toString(),
                        content: message,
                        created_at: new Date().toISOString(),
                        read: true,
                        is_assistant: true,
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
            if (values.chats.find((chat) => chat.id === selectedChatId)?.messages.some((message) => !message.read)) {
                actions.setChats(
                    values.chats.map((chat) => {
                        if (chat.id === selectedChatId) {
                            return { ...chat, messages: chat.messages.map((message) => ({ ...message, read: true })) }
                        }
                        return chat
                    })
                )
            }
        },
    })),
])
