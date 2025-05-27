import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SlackChannelType } from '~/types'

import type { slackIntegrationLogicType } from './slackIntegrationLogicType'

export type SlackErrorType = {
    type: 'auth' | 'rate_limit' | 'api' | 'config' | 'unknown'
    message: string
    details?: any
}

export const slackIntegrationLogic = kea<slackIntegrationLogicType>([
    props({} as { id: number }),
    key((props) => props.id),
    path((key) => ['lib', 'integrations', 'slackIntegrationLogic', key]),
    connect(() => ({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight']],
    })),
    actions({
        loadAllSlackChannels: () => ({}),
        loadSlackChannelById: (channelId: string) => ({ channelId }),
        clearError: () => ({}),
    }),

    loaders(({ props }) => ({
        allSlackChannels: [
            null as SlackChannelType[] | null,
            {
                loadAllSlackChannels: async () => {
                    try {
                        const res = await api.integrations.slackChannels(props.id)
                        return res.channels
                    } catch (error: any) {
                        const errorType = determineErrorType(error)
                        throw errorType
                    }
                },
            },
        ],
        slackChannelById: [
            null as SlackChannelType | null,
            {
                loadSlackChannelById: async ({ channelId }, breakpoint) => {
                    try {
                        await breakpoint(500)
                        const res = await api.integrations.slackChannelsById(props.id, channelId)
                        return res.channels[0] || null
                    } catch (error: any) {
                        const errorType = determineErrorType(error)
                        throw errorType
                    }
                },
            },
        ],
    })),

    reducers({
        _fetchedSlackChannels: [
            [] as SlackChannelType[],
            {
                loadAllSlackChannelsSuccess: (_, { allSlackChannels }) => allSlackChannels ?? [],
            },
        ],
        _fetchedSlackChannelById: [
            null as SlackChannelType | null,
            {
                loadSlackChannelByIdSuccess: (_, { slackChannelById }) => slackChannelById,
            },
        ],
        error: [
            null as SlackErrorType | null,
            {
                loadAllSlackChannelsFailure: (_, { error }) => error as unknown as SlackErrorType,
                loadSlackChannelByIdFailure: (_, { error }) => error as unknown as SlackErrorType,
                clearError: () => null,
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
        hasError: [(s) => [s.error], (error) => error !== null],
        errorMessage: [(s) => [s.error], (error) => error?.message ?? ''],
        isAuthError: [(s) => [s.error], (error) => error?.type === 'auth'],
        isRateLimitError: [(s) => [s.error], (error) => error?.type === 'rate_limit'],
    }),
])

function determineErrorType(error: any): SlackErrorType {
    if (error?.response?.status === 401 || error?.response?.status === 403) {
        return {
            type: 'auth',
            message: 'Authentication failed. Please reconnect your Slack integration.',
            details: error.response?.data,
        }
    }
    if (error?.response?.status === 429 || error?.message?.toLowerCase().includes('rate limit')) {
        return {
            type: 'rate_limit',
            message: 'Slack API rate limit exceeded. Please try again in a few minutes.',
            details: error.response?.data,
        }
    }
    if (error?.response?.data?.error) {
        return {
            type: 'api',
            message: error.response.data.error,
            details: error.response.data,
        }
    }
    return {
        type: 'unknown',
        message: 'An unexpected error occurred while communicating with Slack.',
        details: error,
    }
}
