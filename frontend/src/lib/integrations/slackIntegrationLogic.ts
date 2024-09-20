import { actions, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SlackChannelType } from '~/types'

import type { slackIntegrationLogicType } from './slackIntegrationLogicType'

export const slackIntegrationLogic = kea<slackIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'slackIntegrationLogic', key]),
    connect({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    }),
    actions({
        loadSlackChannels: true,
    }),

    loaders(({ props }) => ({
        slackChannels: [
            null as SlackChannelType[] | null,
            {
                loadSlackChannels: async () => {
                    const res = await api.integrations.slackChannels(props.id)
                    return res.channels
                },
            },
        ],
    })),
    selectors({
        isMemberOfSlackChannel: [
            (s) => [s.slackChannels],
            (slackChannels) => {
                return (channel: string) => {
                    if (!slackChannels) {
                        return null
                    }

                    const [channelId] = channel.split('|')

                    return slackChannels.find((x) => x.id === channelId)?.is_member ?? false
                }
            },
        ],
    }),
])
