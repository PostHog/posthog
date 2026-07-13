import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { getRecentSlackChannelIds, slackChannelId } from 'lib/integrations/slackChannel'
import { preflightLogic } from 'lib/logic/preflightLogic'

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
        loadAllSlackChannels: (forceRefresh: boolean = false, search: string = '') => ({ forceRefresh, search }),
        loadSlackChannelById: (channelId: string) => ({ channelId }),
        setRecentlySubscribedChannelIds: (channelIds: string[]) => ({ channelIds }),
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

    reducers(({ props }) => ({
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
            getRecentSlackChannelIds(props.id),
            {
                setRecentlySubscribedChannelIds: (_, { channelIds }) => channelIds,
            },
        ],
    })),

    listeners(({ props, actions }) => ({
        loadAllSlackChannelsSuccess: () => {
            actions.setRecentlySubscribedChannelIds(getRecentSlackChannelIds(props.id))
        },
    })),

    selectors({
        slackChannels: [
            (s) => [s._fetchedSlackChannels, s._fetchedSlackChannelById],
            (_fetchedSlackChannels, _fetchedSlackChannelById): SlackChannelType[] => {
                const channels = [..._fetchedSlackChannels]
                if (_fetchedSlackChannelById && !channels.find((x) => x.id === _fetchedSlackChannelById.id)) {
                    channels.push(_fetchedSlackChannelById)
                }
                return channels
            },
        ],
        slackChannelsForPicker: [
            (s) => [s.slackChannels, s.recentlySubscribedChannelIds],
            (slackChannels, recentlySubscribedChannelIds): SlackChannelType[] => {
                const recencyIndex = new Map(recentlySubscribedChannelIds.map((id, idx) => [id, idx]))
                return [...slackChannels].sort((a, b) => {
                    const aRecency = recencyIndex.get(a.id) ?? Number.POSITIVE_INFINITY
                    const bRecency = recencyIndex.get(b.id) ?? Number.POSITIVE_INFINITY
                    if (aRecency !== bRecency) {
                        return aRecency - bRecency
                    }
                    // Private channels the bot can't access come back from Slack without a name,
                    // so guard the comparator instead of assuming a string.
                    return (a.name ?? '').localeCompare(b.name ?? '')
                })
            },
        ],
        isMemberOfSlackChannel: [
            (s) => [s.slackChannels],
            (slackChannels: SlackChannelType[]) => {
                return (channel: string): boolean | null => {
                    const found = slackChannels.find((x) => x.id === slackChannelId(channel))
                    // Null when unknown so the picker's strict `=== false` membership gate doesn't fire spuriously.
                    return found ? (found.is_member ?? false) : null
                }
            },
        ],
        isPrivateChannelWithoutAccess: [
            (s) => [s.slackChannels],
            (slackChannels: SlackChannelType[]) => {
                return (channel: string) =>
                    slackChannels.find((x) => x.id === slackChannelId(channel))?.is_private_without_access ?? false
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
