import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { channelsApi } from './api'
import type { channelsLogicType } from './channelsLogicType'
import type { ChatChannel } from './types'

export const channelsLogic = kea<channelsLogicType>([
    path(['products', 'conversations', 'frontend', 'channelsLogic']),
    actions({
        createChannel: (name: string, description?: string) => ({ name, description }),
        joinChannel: (channelId: string) => ({ channelId }),
        leaveChannel: (channelId: string) => ({ channelId }),
        setChannels: (channels: ChatChannel[]) => ({ channels }),
    }),
    loaders({
        channels: [
            [] as ChatChannel[],
            {
                loadChannels: async (): Promise<ChatChannel[]> => {
                    return await channelsApi.list()
                },
            },
        ],
    }),
    reducers({
        channels: {
            setChannels: (_, { channels }) => channels,
        },
    }),
    listeners(({ actions }) => ({
        createChannel: async ({ name, description }) => {
            try {
                await channelsApi.create({ name, description })
                lemonToast.success(`Channel #${name} created`)
                actions.loadChannels()
            } catch (e: any) {
                const detail = e?.data?.name?.[0] || e?.data?.detail || 'Failed to create channel'
                lemonToast.error(detail)
            }
        },
        joinChannel: async ({ channelId }) => {
            try {
                await channelsApi.join(channelId)
                actions.loadChannels()
            } catch {
                lemonToast.error('Failed to join channel')
            }
        },
        leaveChannel: async ({ channelId }) => {
            try {
                await channelsApi.leave(channelId)
                actions.loadChannels()
            } catch (e: any) {
                const detail = e?.data?.detail || 'Failed to leave channel'
                lemonToast.error(detail)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadChannels()
    }),
])
