import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SlackChannelType } from '~/types'

import type { slackIntegrationLogicType } from './slackIntegrationLogicType'

export const SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS = 30
export const RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT = 20

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

export const slackIntegrationLogic = kea<slackIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'slackIntegrationLogic', key]),
    connect(() => ({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    })),
    actions({
        loadAllSlackChannels: (forceRefresh: boolean = false, search: string = '') => ({ forceRefresh, search }),
        loadSlackChannelById: (channelId: string) => ({ channelId }),
        recordSubscribedChannel: (channelId: string) => ({ channelId }),
    }),

    loaders(({ props }) => ({
        allSlackChannels: [
            null as { channels: SlackChannelType[]; lastRefreshedAt: string; has_more?: boolean } | null,
            {
                loadAllSlackChannels: async ({ forceRefresh, search }, breakpoint) => {
                    if (search) {
                        await breakpoint(300)
                    }
                    return await api.integrations.slackChannels(props.id, forceRefresh, { search })
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
        recentlySubscribedChannelIds: [
            [] as string[],
            persistConfig,
            {
                recordSubscribedChannel: (state, { channelId }) => {
                    if (!channelId) {
                        return state
                    }
                    const next = [channelId, ...state.filter((id) => id !== channelId)]
                    return next.slice(0, RECENTLY_SUBSCRIBED_SLACK_CHANNELS_LIMIT)
                },
            },
        ],
    }),

    selectors({
        slackChannels: [
            (s) => [s._fetchedSlackChannels, s._fetchedSlackChannelById, s.recentlySubscribedChannelIds],
            (_fetchedSlackChannels, _fetchedSlackChannelById, recentlySubscribedChannelIds): SlackChannelType[] => {
                const channels = [..._fetchedSlackChannels]
                if (_fetchedSlackChannelById && !channels.find((x) => x.id === _fetchedSlackChannelById.id)) {
                    channels.push(_fetchedSlackChannelById)
                }
                const recencyIndex = new Map(recentlySubscribedChannelIds.map((id, idx) => [id, idx]))
                return channels.sort((a, b) => {
                    const aRecency = recencyIndex.get(a.id) ?? Number.POSITIVE_INFINITY
                    const bRecency = recencyIndex.get(b.id) ?? Number.POSITIVE_INFINITY
                    if (aRecency !== bRecency) {
                        return aRecency - bRecency
                    }
                    return a.name.localeCompare(b.name)
                })
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
