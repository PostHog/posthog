import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PersonPropType } from 'scenes/persons/person-utils'

import type { chatListLogicType } from './chatListLogicType'

export type Chat = {
    id?: string
    person_uuid?: string // email or user id, for dummy data
    distinct_id?: string // email or user id, for dummy data
    person?: PersonPropType
    team: string // team id, for dummy data
    title?: string | null
    created_at: string
    updated_at: string
    source_url?: string | null
    unread_count: number
    messages: ChatMessage[]
}

export type ChatMessage = {
    id?: string
    content: string
    created_at: string
    read: boolean
    is_assistant: boolean
}

export const chatListLogic = kea<chatListLogicType>([
    path(['products', 'chat', 'frontend', 'chatListLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setSelectedChatId: (selectedChatId: string | null) => ({ selectedChatId }),
        setChats: (chats: Chat[]) => ({ chats }),
        sendMessage: (message: string) => ({ message }),
        setMessage: (message: string) => ({ message }),
        loadChats: true,
        loadChat: (chatId: string) => ({ chatId }),
        createZendDeskTicket: (subject: string, uuid: string, message: string) => ({ subject, uuid, message }),
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
                    actions.loadChats()
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
            if (selectedChatId) {
                actions.loadChat(selectedChatId)
            }
        },
        loadChats: async () => {
            const chats = await api.chat.list()
            if (chats.results.length > 0) {
                actions.setChats(chats.results)
            }
        },
        loadChat: async ({ chatId }) => {
            // basically we mark the messages as read
            await api.chat.get(chatId)
        },
        createZendDeskTicket: async ({ subject, uuid, message }) => {
            if (values.featureFlags[FEATURE_FLAGS.FEATURE_CHAT]) {
                const chat = await api.chat.create({
                    //person_uuid: uuid,
                    distinct_id: uuid,
                    title: subject,
                    source_url: 'zendesk',
                })
                if (chat && chat.id) {
                    const newMessage: ChatMessage = {
                        content: message,
                        created_at: new Date().toISOString(),
                        read: false,
                        is_assistant: false,
                    }

                    await api.chat.sendMessage(chat.id, newMessage)
                    actions.loadChats()
                }
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadChats()
    }),
])
