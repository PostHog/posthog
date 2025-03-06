import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SlackChannelType } from '~/types'

import type { slackIntegrationLogicType } from './slackIntegrationLogicType'

export class SlackChannels {
    private fetchedSlackChannels: SlackChannelType[]
    private fetchedSlackChannelById: SlackChannelType | null
    private all: SlackChannelType[]

    constructor(fetchedSlackChannels: SlackChannelType[], fetchedSlackChannelById: SlackChannelType | null) {
        this.fetchedSlackChannels = fetchedSlackChannels
        this.fetchedSlackChannelById = fetchedSlackChannelById
        this.all = [...this.fetchedSlackChannels]
        if (this.fetchedSlackChannelById && !this.all.find((x) => x.id === this.fetchedSlackChannelById!.id)) {
            this.all.push(this.fetchedSlackChannelById)
        }
    }

    withNewChannelById(channel: SlackChannelType): SlackChannels {
        return new SlackChannels(this.fetchedSlackChannels, channel)
    }

    withNewChannels(channels: SlackChannelType[]): SlackChannels {
        return new SlackChannels(channels, this.fetchedSlackChannelById)
    }

    list(): SlackChannelType[] {
        return this.all
    }
}

export const slackIntegrationLogic = kea<slackIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'slackIntegrationLogic', key]),
    connect({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    }),
    actions({
        loadAllSlackChannels: () => ({}),
        loadSlackChannelById: (channelId: string) => ({ channelId }),
    }),

    loaders(({ props }) => ({
        allSlackChannels: [
            null as SlackChannelType[] | null,
            {
                loadAllSlackChannels: async () => {
                    const res = await api.integrations.slackChannels(props.id)
                    return res.channels
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
        slackChannels: [
            new SlackChannels([], null),
            {
                loadSlackChannelByIdSuccess: (
                    state: SlackChannels,
                    { slackChannelById }: { slackChannelById: SlackChannelType }
                ) => {
                    return state.withNewChannelById(slackChannelById)
                },
                loadAllSlackChannelsSuccess: (
                    state: SlackChannels,
                    { allSlackChannels }: { allSlackChannels: SlackChannelType[] }
                ) => {
                    return state.withNewChannels(allSlackChannels)
                },
            },
        ],
    }),

    selectors({
        isMemberOfSlackChannel: [
            (s) => [s.slackChannels],
            (slackChannels: SlackChannels) => {
                return (channel: string) => {
                    const [channelId] = channel.split('|')
                    return slackChannels.list().find((x) => x.id === channelId)?.is_member ?? false
                }
            },
        ],
    }),
])
