import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { CommentType } from '~/types'

import { commentsSendToSlackCreate } from 'products/platform_features/frontend/generated/api'

import type { sendCommentToSlackLogicType } from './sendCommentToSlackLogicType'

export const sendCommentToSlackLogic = kea<sendCommentToSlackLogicType>([
    path(['scenes', 'comments', 'sendCommentToSlackLogic']),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        openModal: (comment: CommentType) => ({ comment }),
        closeModal: true,
        setIntegrationId: (integrationId: number | null) => ({ integrationId }),
        // SlackChannelPicker emits a "CHANNEL_ID|#name" composite; we keep it whole for display.
        setChannel: (channel: string | null) => ({ channel }),
        submit: true,
        submitSuccess: true,
        submitFailure: true,
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
    }),
    listeners(({ actions, values }) => ({
        submit: async () => {
            const { comment, integrationId, channelId, currentTeamId } = values
            if (!comment || !integrationId || !channelId || !currentTeamId) {
                actions.submitFailure()
                return
            }
            try {
                await commentsSendToSlackCreate(String(currentTeamId), comment.id, {
                    integration_id: integrationId,
                    channel_id: channelId,
                })
                actions.submitSuccess()
            } catch {
                actions.submitFailure()
            }
        },
        submitSuccess: () => {
            lemonToast.success('Discussion sent to Slack')
        },
        submitFailure: () => {
            lemonToast.error('Could not send the discussion to Slack')
        },
    })),
])
