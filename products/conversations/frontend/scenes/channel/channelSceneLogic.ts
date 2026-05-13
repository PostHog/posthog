import { JSONContent } from '@tiptap/core'
import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from '~/lib/api'
import type { CommentType } from '~/types'

import { channelsApi } from '../../api'
import type { ChatChannel, ChatChannelMember, ChatMessage } from '../../types'
import type { channelSceneLogicType } from './channelSceneLogicType'

const MESSAGE_POLL_INTERVAL = 5000

export const channelSceneLogic = kea<channelSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'channel', 'channelSceneLogic']),
    props({ channelId: '' as string }),
    key((props) => props.channelId),
    actions({
        loadChannel: true,
        setChannel: (channel: ChatChannel | null) => ({ channel }),
        setChannelLoading: (loading: boolean) => ({ loading }),

        loadMessages: true,
        setMessages: (messages: CommentType[]) => ({ messages }),
        setMessagesLoading: (loading: boolean) => ({ loading }),

        sendMessage: (content: string, richContent: JSONContent | null, onSuccess?: () => void) => ({
            content,
            richContent,
            onSuccess,
        }),
        setMessageSending: (sending: boolean) => ({ sending }),

        loadMembers: true,
        setMembers: (members: ChatChannelMember[]) => ({ members }),

        setDraftContent: (content: JSONContent | null) => ({ content }),
    }),
    reducers({
        channel: [
            null as ChatChannel | null,
            {
                setChannel: (_, { channel }) => channel,
            },
        ],
        channelLoading: [
            true,
            {
                loadChannel: () => true,
                setChannel: () => false,
                setChannelLoading: (_, { loading }) => loading,
            },
        ],
        messages: [
            [] as CommentType[],
            {
                setMessages: (_, { messages }) => messages,
            },
        ],
        messagesLoading: [
            false,
            {
                loadMessages: () => true,
                setMessages: () => false,
                setMessagesLoading: (_, { loading }) => loading,
            },
        ],
        messageSending: [
            false,
            {
                sendMessage: () => true,
                setMessageSending: (_, { sending }) => sending,
            },
        ],
        members: [
            [] as ChatChannelMember[],
            {
                setMembers: (_, { members }) => members,
            },
        ],
        draftContent: [
            null as JSONContent | null,
            {
                setDraftContent: (_, { content }) => content,
            },
        ],
    }),
    selectors({
        chatMessages: [
            (s) => [s.messages],
            (messages: CommentType[]): ChatMessage[] =>
                messages.map((message) => {
                    let displayName = 'Unknown user'
                    if (message.created_by) {
                        displayName =
                            [message.created_by.first_name, message.created_by.last_name].filter(Boolean).join(' ') ||
                            message.created_by.email ||
                            'Unknown user'
                    }

                    return {
                        id: message.id,
                        content: message.content || '',
                        richContent: message.rich_content,
                        authorType: 'human',
                        authorName: displayName,
                        createdBy: message.created_by,
                        createdAt: message.created_at,
                    }
                }),
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
        loadChannel: async () => {
            try {
                const channel = await channelsApi.get(props.channelId)
                actions.setChannel(channel)
                actions.loadMessages()
                actions.loadMembers()

                cache.disposables.dispose('messagePolling')
                cache.disposables.add(() => {
                    const intervalId = setInterval(() => {
                        actions.loadMessages()
                    }, MESSAGE_POLL_INTERVAL)
                    return () => clearInterval(intervalId)
                }, 'messagePolling')
            } catch {
                lemonToast.error('Failed to load channel')
                actions.setChannelLoading(false)
            }
        },
        loadMessages: async () => {
            if (!values.channel?.id) {
                actions.setMessages([])
                return
            }
            try {
                const response = await api.comments.list({
                    scope: 'conversations_channel',
                    item_id: values.channel.id,
                })
                actions.setMessages((response.results || []).reverse())
            } catch {
                lemonToast.error('Failed to load messages')
                actions.setMessagesLoading(false)
            }
        },
        sendMessage: async ({ content, richContent, onSuccess }) => {
            if (!values.channel?.id) {
                actions.setMessageSending(false)
                return
            }
            try {
                await api.comments.create(
                    {
                        content,
                        rich_content: richContent,
                        scope: 'conversations_channel',
                        item_id: values.channel.id,
                        item_context: {
                            author_type: 'support',
                        },
                    },
                    {}
                )
                actions.setMessageSending(false)
                onSuccess?.()
                setTimeout(() => {
                    actions.loadMessages()
                }, 300)
            } catch {
                lemonToast.error('Failed to send message')
                actions.setMessageSending(false)
            }
        },
        loadMembers: async () => {
            if (!props.channelId) {
                return
            }
            try {
                const members = await channelsApi.members(props.channelId)
                actions.setMembers(members)
            } catch {
                // non-critical
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadChannel()
    }),
    beforeUnmount(({ cache }) => {
        cache.disposables.disposeAll()
    }),
])
