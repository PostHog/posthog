import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import { defaultConfig } from '~/common/config/config'

import { registerAsyncFunction } from '../async-function-registry'
import { PosthogJwtAudience } from '../utils/jwt-utils'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { workflowStepDispatchKeyFromInvocation } from '../utils/workflow-step-dispatch-key'
import { callInternalApi } from './internal-api-call'

let slackDmTeamMemberJwt: ScopedServiceJwt | undefined
const getSlackDmTeamMemberJwt = (): ScopedServiceJwt =>
    (slackDmTeamMemberJwt ??= new ScopedServiceJwt(
        PosthogJwtAudience.WORKFLOW_SLACK_DM_TEAM_MEMBER,
        defaultConfig.WORKFLOW_SLACK_DM_TEAM_MEMBER_JWT_SECRET
    ))

type SlackDmTeamMemberPayload = {
    integration_id: number
    recipient: string
    text: string
    button_url: string
    button_text: string
}

// The step test panel mocks async functions by default, so `mock` runs these checks too.
const parsePayload = (args: any[]): SlackDmTeamMemberPayload => {
    const [payload] = args as [Record<string, unknown> | undefined]
    const integrationId = payload?.integration_id
    if (typeof integrationId !== 'number' || !Number.isSafeInteger(integrationId) || integrationId < 1) {
        throw new Error('Choose a Slack workspace')
    }
    const text = typeof payload?.text === 'string' ? payload.text.trim() : ''
    if (!text) {
        throw new Error('Write a message')
    }
    const asString = (value: unknown): string => (typeof value === 'string' ? value.trim() : '')
    return {
        integration_id: integrationId,
        recipient: asString(payload?.recipient),
        text,
        button_url: asString(payload?.button_url),
        button_text: asString(payload?.button_text),
    }
}

registerAsyncFunction('postHogSlackDmTeamMember', {
    execute: async (args, context, result) => {
        const payload = parsePayload(args)

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        const idempotencyKey = workflowStepDispatchKeyFromInvocation(context.invocation)
        if (!hogFlow?.id || !idempotencyKey) {
            throw new Error('Message team member on Slack only runs inside a workflow')
        }

        const jwt = getSlackDmTeamMemberJwt()
        if (!jwt.enabled) {
            throw new Error(
                'Message team member on Slack is not configured. Set WORKFLOW_SLACK_DM_TEAM_MEMBER_JWT_SECRET on the worker and Django to matching keys.'
            )
        }
        // A retry of the same step execution replays the first send, so Django never sends the message twice.
        await callInternalApi(context, result, {
            jwt,
            path: `/api/projects/${context.invocation.teamId}/workflow_slack_team_member_messages/`,
            method: 'POST',
            entityClaims: { hog_flow_id: hogFlow.id },
            body: JSON.stringify({ ...payload, idempotency_key: idempotencyKey }),
            retriableStatuses: [409],
        })
    },
    mock: (args, logs) => {
        parsePayload(args)
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: 'Message team member on Slack was mocked. Nobody was sent a message.',
        })
        return { status: 200, body: { outcome: 'sent', detail: 'The message was sent.', slack_user_id: 'U0MOCK' } }
    },
})
