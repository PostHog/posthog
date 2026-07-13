import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { announcementsChannelsList, announcementsCreate, announcementsList } from '../../generated/api'
import type { AnnouncementApi, AnnouncementChannelApi } from '../../generated/api.schemas'
// NonReadonly<AnnouncementApi> resolves to just the writable fields ({ message, channels }).
import type { announcementsLogicType } from './announcementsLogicType'

export const announcementsLogic = kea<announcementsLogicType>([
    path(['products', 'customer_analytics', 'frontend', 'components', 'Announcements', 'announcementsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        setMessage: (message: string) => ({ message }),
        setSelectedChannelIds: (channelIds: string[]) => ({ channelIds }),
        submitAnnouncement: true,
        setSubmitting: (submitting: boolean) => ({ submitting }),
    }),
    loaders(({ values }) => ({
        announcements: [
            [] as AnnouncementApi[],
            {
                loadAnnouncements: async () => {
                    const response = await announcementsList(String(values.currentTeam?.id), { limit: 100 })
                    return response.results ?? []
                },
            },
        ],
        memberChannels: [
            [] as AnnouncementChannelApi[],
            {
                loadMemberChannels: async () => {
                    try {
                        return await announcementsChannelsList(String(values.currentTeam?.id))
                    } catch {
                        lemonToast.error('Failed to load Slack channels')
                        return values.memberChannels
                    }
                },
            },
        ],
    })),
    reducers({
        messageDraft: ['', { setMessage: (_state, { message }) => message }],
        selectedChannelIds: [[] as string[], { setSelectedChannelIds: (_state, { channelIds }) => channelIds }],
        submitting: [false, { setSubmitting: (_state, { submitting }) => submitting }],
    }),
    selectors({
        slackConnected: [
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
        submitAnnouncement: async () => {
            // Guard against double-submission while a send is in flight.
            if (values.submitting || values.submitDisabledReason) {
                return
            }
            actions.setSubmitting(true)
            try {
                await announcementsCreate(String(values.currentTeam?.id), {
                    message: values.messageDraft.trim(),
                    channels: values.selectedChannelIds,
                })
                lemonToast.success('Announcement sent')
                actions.setMessage('')
                actions.setSelectedChannelIds([])
                actions.loadAnnouncements()
            } catch {
                lemonToast.error('Failed to send announcement')
            } finally {
                actions.setSubmitting(false)
            }
        },
    })),
    afterMount(({ values, actions }) => {
        actions.loadAnnouncements()
        if (values.slackConnected) {
            actions.loadMemberChannels()
        }
    }),
])
