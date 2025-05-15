import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'

import type { chatListLogicType } from './chatListLogicType'

export type Chat = {
    id?: string
    person_uuid: string // email or user id, for dummy data
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
        loadChats: true,
        loadChatMessages: (conversationId: string) => ({ conversationId }),
    }),
    reducers({
        chats: [
            [] as Chat[],
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
        sendMessage: async ({ message }) => {
            if (values.selectedChatId) {
                const chat = values.chats.find((chat) => chat.id === values.selectedChatId)
                if (chat) {
                    const newMessage: ChatMessage = {
                        content: message,
                        created_at: new Date().toISOString(),
                        read: true,
                        is_assistant: true,
                    }

                    await api.chat.sendMessage(values.selectedChatId, newMessage)

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
            //actions.loadChatMessages(selectedChatId)
        },
        loadChats: async () => {
            const chats = await api.chat.list()
            if (chats.results.length > 0) {
                actions.setChats(chats.results)
            }
        },
        loadChatMessages: async ({ conversationId }) => {
            await api.chat.listMessages(conversationId)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadChats()
    }),
])
