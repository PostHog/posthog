import { DateTime } from 'luxon'

import {
    CyclotronInvocationQueueParametersEmailCaptureType,
    CyclotronInvocationQueueParametersEmailType,
} from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '~/cdp/types'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent, isFeatureFlagEnabled } from '~/common/utils/posthog'
import { internalFetch } from '~/common/utils/request'
import { TeamManager } from '~/common/utils/team-manager'

const CUSTOMER_ANALYTICS_CSP_FLAG = 'customer-analytics-csp'
export const ELIGIBILITY_TIMEOUT_MS = 2 * 60 * 1000
const ELIGIBILITY_RETRY_MS = 10 * 1000
const CAPTURE_RETRY_MAX_MS = 30 * 60 * 1000
const CAPTURE_MAX_AGE_MS = 24 * 60 * 60 * 1000

type EligibilityResult = 'ineligible' | 'eligible' | 'retry'

export class WorkflowConversationCaptureService {
    constructor(
        private teamManager: TeamManager,
        private jwt: ScopedServiceJwt,
        private internalApiBaseUrl: string
    ) {}

    async checkEligibility(
        teamId: number,
        sourceId: string,
        integrationId: number,
        sender: { email: string; name: string },
        to: { email: string; name: string },
        cc: { email: string; name: string }[]
    ): Promise<EligibilityResult> {
        let timeout: NodeJS.Timeout | undefined
        try {
            return await Promise.race([
                this.checkEligibilityOnce(teamId, sourceId, integrationId, sender, to, cc),
                new Promise<EligibilityResult>((resolve) => {
                    timeout = setTimeout(() => resolve('retry'), 5000)
                }),
            ])
        } finally {
            if (timeout) {
                clearTimeout(timeout)
            }
        }
    }

    private async checkEligibilityOnce(
        teamId: number,
        sourceId: string,
        integrationId: number,
        sender: { email: string; name: string },
        to: { email: string; name: string },
        cc: { email: string; name: string }[]
    ): Promise<EligibilityResult> {
        if (!this.jwt.enabled) {
            return 'ineligible'
        }
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (!team) {
                return 'ineligible'
            }
            const enabled = await isFeatureFlagEnabled(
                CUSTOMER_ANALYTICS_CSP_FLAG,
                team.organization_id,
                {
                    groups: { organization: team.organization_id },
                    onlyEvaluateLocally: false,
                    sendFeatureFlagEvents: false,
                },
                true
            )
            if (!enabled) {
                return 'ineligible'
            }
        } catch {
            return 'retry'
        }
        try {
            const response = await internalFetch(
                `${this.internalApiBaseUrl}/api/projects/${teamId}/internal/conversations/workflow-emails/eligible`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: `Bearer ${this.jwt.mint({ team_id: teamId, source_id: sourceId })}`,
                    },
                    body: JSON.stringify({ source_id: sourceId, email_integration_id: integrationId, sender, to, cc }),
                    timeoutMs: 5000,
                }
            )
            if (response.status === 200) {
                const body: unknown = await response.json()
                if (body && typeof body === 'object' && 'eligible' in body && typeof body.eligible === 'boolean') {
                    return body.eligible ? 'eligible' : 'ineligible'
                }
                return 'retry'
            }
            if (response.status >= 500 || response.status === 429) {
                return 'retry'
            }
            logger.warn('workflow_conversation_eligibility_rejected', { teamId, sourceId, status: response.status })
            return 'ineligible'
        } catch {
            return 'retry'
        }
    }

    getEligibilityDelay(params: CyclotronInvocationQueueParametersEmailType, now = Date.now()): number | null {
        const firstFailure = Date.parse(params.conversationEligibilityFirstFailedAt ?? '')
        if (!Number.isFinite(firstFailure)) {
            params.conversationEligibilityFirstFailedAt = new Date(now).toISOString()
            return ELIGIBILITY_RETRY_MS
        }
        const remaining = ELIGIBILITY_TIMEOUT_MS - (now - firstFailure)
        return remaining > 0 ? Math.min(ELIGIBILITY_RETRY_MS, remaining) : null
    }

    async recordSkipped(
        teamId: number,
        invocationId: string,
        reason:
            | 'eligibility_timeout'
            | 'body_unavailable'
            | 'queue_unavailable'
            | 'unmatched_after_send'
            | 'disabled_after_send'
    ): Promise<void> {
        logger.warn('workflow_conversation_capture_skipped', { teamId, invocationId, reason })
        const team = await this.teamManager.getTeam(teamId)
        if (team) {
            captureTeamEvent(team, 'workflow_conversation_capture_skipped', {
                reason,
                invocation_id: invocationId,
            })
        }
    }

    async recordTerminalFailure(teamId: number, sourceId: string, reason: 'expired' | 'rejected'): Promise<void> {
        logger.error('workflow_conversation_capture_failed', { teamId, sourceId, reason })
        const team = await this.teamManager.getTeam(teamId)
        if (team) {
            captureTeamEvent(team, 'workflow_conversation_capture_failed', {
                reason,
                invocation_id: sourceId,
            })
        }
    }

    async executeCapture(
        invocation: CyclotronJobInvocation
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocation>> {
        const params = invocation.queueParameters as CyclotronInvocationQueueParametersEmailCaptureType
        const result = createInvocationResult(
            invocation,
            { queuePriority: invocation.queuePriority },
            { finished: true }
        )
        result.skipMonitoring = true
        const sentAt = Date.parse(params.capture.sent_at)
        if (!Number.isFinite(sentAt) || Date.now() - sentAt >= CAPTURE_MAX_AGE_MS) {
            void this.recordTerminalFailure(invocation.teamId, params.capture.source_id, 'expired').catch(() => {})
            return result
        }
        try {
            if (!this.jwt.enabled) {
                throw new Error('Workflow conversation service JWT unavailable')
            }
            const response = await internalFetch(
                `${this.internalApiBaseUrl}/api/projects/${invocation.teamId}/internal/conversations/workflow-emails`,
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: `Bearer ${this.jwt.mint({ team_id: invocation.teamId, source_id: params.capture.source_id })}`,
                    },
                    body: JSON.stringify(params.capture),
                    timeoutMs: 5000,
                }
            )
            if (response.status === 200) {
                const body: unknown = await response.json()
                const status = body && typeof body === 'object' && 'status' in body ? body.status : null
                if (status === 'created' || status === 'existing') {
                    return result
                }
                if (status === 'skipped_unmatched' || status === 'skipped_disabled') {
                    void this.recordSkipped(
                        invocation.teamId,
                        params.capture.source_id,
                        status === 'skipped_unmatched' ? 'unmatched_after_send' : 'disabled_after_send'
                    ).catch(() => {})
                    return result
                }
            }
            if (response.status < 500 && response.status !== 429 && response.status !== 200) {
                void this.recordTerminalFailure(invocation.teamId, params.capture.source_id, 'rejected').catch(() => {})
                return result
            }
        } catch {
            // The send has completed. Only this capture job can retry.
        }
        const attempts = params.attempts + 1
        result.finished = false
        result.invocation.queueParameters = { ...params, attempts }
        result.invocation.queueScheduledAt = DateTime.utc().plus({
            milliseconds: Math.min(CAPTURE_RETRY_MAX_MS, 1000 * 2 ** Math.min(attempts, 11)),
        })
        return result
    }
}
