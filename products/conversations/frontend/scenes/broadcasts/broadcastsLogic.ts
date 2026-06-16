import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { SlackChannelType } from '~/types'

import { conversationsBroadcastsCreate, conversationsBroadcastsList } from '../../generated/api'
import type { BroadcastApi } from '../../generated/api.schemas'
import type { broadcastsLogicType } from './broadcastsLogicType'

export const broadcastsLogic = kea<broadcastsLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'broadcasts', 'broadcastsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        setMessage: (message: string) => ({ message }),
        setSelectedChannelIds: (channelIds: string[]) => ({ channelIds }),
        submitBroadcast: true,
        setSubmitting: (submitting: boolean) => ({ submitting }),
    }),
    loaders(({ values }) => ({
        broadcasts: [
            [] as BroadcastApi[],
            {
                loadBroadcasts: async () => {
                    const response = await conversationsBroadcastsList(String(values.currentTeam?.id), { limit: 100 })
                    return response.results ?? []
                },
            },
        ],
        memberChannels: [
            [] as SlackChannelType[],
            {
                loadMemberChannels: async () => {
                    try {
                        // nosemgrep: prefer-codegen-api -- bespoke SupportHog APIView, not a router viewset
                        const response = await api.create('api/conversations/v1/slack/channels', { members_only: true })
                        return response.channels ?? []
                    } catch {
                        lemonToast.error('Failed to load Slack channels')
                        return values.memberChannels
                    }
                },
            },
        ],
    })),
    reducers({
        messageDraft: [
            '',
            {
                setMessage: (_state, { message }) => message,
            },
        ],
        selectedChannelIds: [
            [] as string[],
            {
                setSelectedChannelIds: (_state, { channelIds }) => channelIds,
            },
        ],
        submitting: [
            false,
            {
                setSubmitting: (_state, { submitting }) => submitting,
            },
        ],
    }),
    selectors({
        slackEnabled: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam?.conversations_settings?.slack_enabled,
        ],
        submitDisabledReason: [
            (s) => [s.messageDraft, s.selectedChannelIds, s.submitting],
            (messageDraft, selectedChannelIds, submitting): string | undefined => {
                if (submitting) {
                    return 'Sending…'
                }
                if (!messageDraft.trim()) {
                    return 'Enter a message'
                }
                if (selectedChannelIds.length === 0) {
                    return 'Select at least one channel'
                }
                return undefined
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        submitBroadcast: async () => {
            // Guard against double-submission while a send is in flight.
            if (values.submitting || values.submitDisabledReason) {
                return
            }
            actions.setSubmitting(true)
            try {
                const channels = values.selectedChannelIds.map((id) => {
                    const channel = values.memberChannels.find((c) => c.id === id)
                    return { id, name: channel?.name ?? '' }
                })
                await conversationsBroadcastsCreate(String(values.currentTeam?.id), {
                    message: values.messageDraft.trim(),
                    channels,
                })
                lemonToast.success('Broadcast sent')
                actions.setMessage('')
                actions.setSelectedChannelIds([])
                actions.loadBroadcasts()
            } catch {
                lemonToast.error('Failed to send broadcast')
            } finally {
                actions.setSubmitting(false)
            }
        },
    })),
    afterMount(({ values, actions }) => {
        actions.loadBroadcasts()
        if (values.slackEnabled) {
            actions.loadMemberChannels()
        }
    }),
])
