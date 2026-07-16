import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { CommentType } from '~/types'

import { commentsSendToSlackCreate } from 'products/platform_features/frontend/generated/api'

import type { sendCommentToSlackLogicType } from './sendCommentToSlackLogicType'

export const sendCommentToSlackLogic = kea<sendCommentToSlackLogicType>([
    path(['scenes', 'comments', 'sendCommentToSlackLogic']),
    connect(() => ({ values: [teamLogic, ['currentProjectId']] })),
    actions({
        openModal: (comment: CommentType) => ({ comment }),
        closeModal: true,
        setIntegrationId: (integrationId: number | null) => ({ integrationId }),
        // SlackChannelPicker emits a "CHANNEL_ID|#name" composite; we keep it whole for display.
        setChannel: (channel: string | null) => ({ channel }),
        submit: true,
        submitSuccess: true,
        submitFailure: (detail: string | null = null) => ({ detail }),
    }),
    reducers({
        comment: [
            null as CommentType | null,
            {
                openModal: (_, { comment }) => comment,
                closeModal: () => null,
                submitSuccess: () => null,
            },
        ],
        integrationId: [
            null as number | null,
            {
                setIntegrationId: (_, { integrationId }) => integrationId,
                openModal: () => null,
                closeModal: () => null,
            },
        ],
        channel: [
            null as string | null,
            {
                setChannel: (_, { channel }) => channel,
                setIntegrationId: () => null,
                openModal: () => null,
                closeModal: () => null,
            },
        ],
        isSubmitting: [
            false,
            {
                submit: () => true,
                submitSuccess: () => false,
                submitFailure: () => false,
            },
        ],
    }),
    selectors({
        isOpen: [(s) => [s.comment], (comment): boolean => comment !== null],
        channelId: [(s) => [s.channel], (channel): string | null => (channel ? channel.split('|')[0] : null)],
        channelName: [(s) => [s.channel], (channel): string => channel?.split('|')[1]?.replace(/^#/, '') ?? ''],
    }),
    listeners(({ actions, values }) => ({
        submit: async () => {
            const { comment, integrationId, channelId, channelName, currentProjectId } = values
            if (!comment || !integrationId || !channelId || !currentProjectId) {
                actions.submitFailure()
                return
            }
            try {
                // The comments API is project-scoped — currentTeamId diverges from the project id
                // for non-default environments and 404s.
                await commentsSendToSlackCreate(String(currentProjectId), comment.id, {
                    integration_id: integrationId,
                    channel_id: channelId,
                    channel_name: channelName,
                })
                actions.submitSuccess()
            } catch (e) {
                // Surface the backend's actionable detail (bot not in channel, integration missing…)
                actions.submitFailure(e instanceof ApiError ? e.detail : null)
            }
        },
        submitSuccess: () => {
            lemonToast.success('Discussion sent to Slack')
        },
        submitFailure: ({ detail }) => {
            lemonToast.error(detail || 'Could not send the discussion to Slack')
        },
    })),
])
