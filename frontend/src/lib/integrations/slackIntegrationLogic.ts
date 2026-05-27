import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SlackChannelType } from '~/types'

import type { slackIntegrationLogicType } from './slackIntegrationLogicType'

export const SLACK_CHANNELS_MIN_REFRESH_INTERVAL_SECONDS = 30

// Matches the channels endpoint's max page size (SlackChannelsQuerySerializer.limit).
const SLACK_CHANNELS_PAGE_SIZE = 200

// Safety bound on the pagination loop. The backend caps list_channels at 10k public +
// 10k private channels, so 100 pages covers any real workspace; the cap only guards
// against a runaway loop if the endpoint ever returns has_more incorrectly.
const SLACK_CHANNELS_MAX_PAGES = 100

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
    }),

    loaders(({ props }) => ({
        allSlackChannels: [
            null as { channels: SlackChannelType[]; lastRefreshedAt: string } | null,
            {
                loadAllSlackChannels: async ({ forceRefresh }) => {
                    // The channels endpoint is paginated, so walk every page to build the full
                    // channel list for client-side filtering. Only force a refresh on the first
                    // page — later pages read the cache that first page populated.
                    const channels: SlackChannelType[] = []
                    let offset = 0
                    let lastRefreshedAt = ''
                    for (let page = 0; page < SLACK_CHANNELS_MAX_PAGES; page++) {
                        const res = await api.integrations.slackChannels(props.id, forceRefresh && offset === 0, {
                            limit: SLACK_CHANNELS_PAGE_SIZE,
                            offset,
                        })
                        channels.push(...res.channels)
                        lastRefreshedAt = res.lastRefreshedAt
                        if (!res.has_more) {
                            break
                        }
                        offset += SLACK_CHANNELS_PAGE_SIZE
                    }
                    return { channels, lastRefreshedAt }
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
    }),

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
