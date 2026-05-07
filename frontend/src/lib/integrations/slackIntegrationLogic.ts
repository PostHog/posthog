import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { integrationsChannelsRetrieve } from 'products/integrations/frontend/generated/api'
import type { SlackChannelApi, SlackChannelsResponseApi } from 'products/integrations/frontend/generated/api.schemas'

import type { slackIntegrationLogicType } from './slackIntegrationLogicType'

export const SLACK_CHANNELS_MIN_REFRESH_INTERVAL_MINUTES = 5

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
            null as SlackChannelsResponseApi | null,
            {
                loadAllSlackChannels: async ({ forceRefresh }) => {
                    return await integrationsChannelsRetrieve(String(getCurrentTeamId()), props.id, {
                        force_refresh: forceRefresh,
                    })
                },
            },
        ],
        slackChannelById: [
            null as SlackChannelApi | null,
            {
                loadSlackChannelById: async ({ channelId }, breakpoint) => {
                    await breakpoint(500)
                    const res = await integrationsChannelsRetrieve(String(getCurrentTeamId()), props.id, {
                        channel_id: channelId,
                    })
                    return res.channels[0] || null
                },
            },
        ],
    })),

    reducers({
        _fetchedSlackChannels: [
            [] as SlackChannelApi[],
            {
                loadAllSlackChannelsSuccess: (_, { allSlackChannels }) => allSlackChannels.channels ?? [],
            },
        ],
        _fetchedSlackChannelById: [
            null as SlackChannelApi | null,
            {
                loadSlackChannelByIdSuccess: (_, { slackChannelById }) => slackChannelById,
            },
        ],
    }),

    selectors({
        slackChannels: [
            (s) => [s._fetchedSlackChannels, s._fetchedSlackChannelById],
            (_fetchedSlackChannels, _fetchedSlackChannelById): SlackChannelApi[] => {
                const channels = [..._fetchedSlackChannels]
                if (_fetchedSlackChannelById && !channels.find((x) => x.id === _fetchedSlackChannelById.id)) {
                    channels.push(_fetchedSlackChannelById)
                }
                return channels
            },
        ],
        isMemberOfSlackChannel: [
            (s) => [s.slackChannels],
            (slackChannels: SlackChannelApi[]) => {
                return (channel: string) => {
                    const [channelId] = channel.split('|')
                    return slackChannels.find((x) => x.id === channelId)?.is_member ?? false
                }
            },
        ],
        isPrivateChannelWithoutAccess: [
            (s) => [s.slackChannels],
            (slackChannels: SlackChannelApi[]) => {
                return (channel: string) => {
                    const [channelId] = channel.split('|')
                    return slackChannels.find((x) => x.id === channelId)?.is_private_without_access ?? false
                }
            },
        ],
        getChannelRefreshButtonDisabledReason: [
            (s) => [s.allSlackChannels],
            (allSlackChannels: SlackChannelsResponseApi | null) => (): string => {
                const now = dayjs()
                if (allSlackChannels?.lastRefreshedAt) {
                    const earliestRefresh = dayjs(allSlackChannels.lastRefreshedAt).add(
                        SLACK_CHANNELS_MIN_REFRESH_INTERVAL_MINUTES,
                        'minutes'
                    )
                    if (now.isBefore(earliestRefresh)) {
                        return `You can refresh the channels again ${earliestRefresh.from(now)}`
                    }
                }
                return ''
            },
        ],
    }),
])
