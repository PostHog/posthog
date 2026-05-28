import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SlackChannelType } from '~/types'

import type { slackIntegrationLogicType } from './slackIntegrationLogicType'

export const SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS = 30

export const slackIntegrationLogic = kea<slackIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'slackIntegrationLogic', key]),
    connect(() => ({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    })),
    actions({
        loadAllSlackChannels: (forceRefresh: boolean = false) => ({ forceRefresh }),
        loadSlackChannelById: (channelId: string) => ({ channelId }),
        loadSlackChannelsBySearch: (search: string) => ({ search }),
        clearSlackChannelsBySearch: true,
    }),

    loaders(({ props }) => ({
        allSlackChannels: [
            null as { channels: SlackChannelType[]; lastRefreshedAt: string } | null,
            {
                loadAllSlackChannels: async ({ forceRefresh }) => {
                    return await api.integrations.slackChannels(props.id, forceRefresh)
                },
            },
        ],
        slackChannelById: [
            null as SlackChannelType | null,
            {
                loadSlackChannelById: async ({ channelId }, breakpoint) => {
                    await breakpoint(500)
                    const res = await api.integrations.slackChannelsById(props.id, channelId)
                    return res.channels[0] || null
                },
            },
        ],
        slackChannelsBySearch: [
            [] as SlackChannelType[],
            {
                loadSlackChannelsBySearch: async ({ search }, breakpoint) => {
                    await breakpoint(300)
                    if (!search) {
                        return []
                    }
                    const res = await api.integrations.slackChannelsBySearch(props.id, search)
                    // Discard stale responses — a faster later query may have already resolved.
                    breakpoint()
                    return res.channels ?? []
                },
            },
        ],
    })),

    reducers({
        _fetchedSlackChannels: [
            [] as SlackChannelType[],
            {
                loadAllSlackChannelsSuccess: (_, { allSlackChannels }) => allSlackChannels.channels ?? [],
            },
        ],
        _fetchedSlackChannelById: [
            null as SlackChannelType | null,
            {
                loadSlackChannelByIdSuccess: (_, { slackChannelById }) => slackChannelById,
            },
        ],
        _fetchedSlackChannelsBySearch: [
            [] as SlackChannelType[],
            {
                loadSlackChannelsBySearchSuccess: (_, { slackChannelsBySearch }) => slackChannelsBySearch ?? [],
                clearSlackChannelsBySearch: () => [],
            },
        ],
    }),

    listeners(() => ({
        loadSlackChannelsBySearchFailure: ({ error }) => {
            // Surface failures so the picker doesn't masquerade them as an "install the app" empty state.
            lemonToast.error(`Couldn't search Slack channels: ${error || 'unknown error'}`)
        },
    })),

    selectors({
        slackChannels: [
            (s) => [s._fetchedSlackChannels, s._fetchedSlackChannelById, s._fetchedSlackChannelsBySearch],
            (_fetchedSlackChannels, _fetchedSlackChannelById, _fetchedSlackChannelsBySearch): SlackChannelType[] => {
                const channels = [..._fetchedSlackChannels]
                const seen = new Set(channels.map((x) => x.id))
                for (const channel of _fetchedSlackChannelsBySearch) {
                    if (!seen.has(channel.id)) {
                        channels.push(channel)
                        seen.add(channel.id)
                    }
                }
                if (_fetchedSlackChannelById && !seen.has(_fetchedSlackChannelById.id)) {
                    channels.push(_fetchedSlackChannelById)
                }
                return channels
            },
        ],
        isMemberOfSlackChannel: [
            (s) => [s.slackChannels],
            (slackChannels: SlackChannelType[]) => {
                return (channel: string) => {
                    const [channelId] = channel.split('|')
                    return slackChannels.find((x) => x.id === channelId)?.is_member ?? false
                }
            },
        ],
        isPrivateChannelWithoutAccess: [
            (s) => [s.slackChannels],
            (slackChannels: SlackChannelType[]) => {
                return (channel: string) => {
                    const [channelId] = channel.split('|')
                    return slackChannels.find((x) => x.id === channelId)?.is_private_without_access ?? false
                }
            },
        ],
        getChannelRefreshButtonDisabledReason: [
            (s) => [s.allSlackChannels],
            (allSlackChannels: { channels: SlackChannelType[]; lastRefreshedAt: string } | null) => (): string => {
                const now = dayjs()
                if (allSlackChannels) {
                    const earliestRefresh = dayjs(allSlackChannels.lastRefreshedAt).add(
                        SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS,
                        'seconds'
                    )
                    if (now.isBefore(earliestRefresh)) {
                        const secondsLeft = Math.ceil(earliestRefresh.diff(now) / 1000)
                        return `You can refresh the channels again in ${secondsLeft} second${
                            secondsLeft === 1 ? '' : 's'
                        }`
                    }
                }
                return ''
            },
        ],
    }),
])
