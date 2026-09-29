import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersEmailCaptureType } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '~/cdp/types'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { internalFetch } from '~/common/utils/request'
import { TeamManager } from '~/common/utils/team-manager'

const CAPTURE_RETRY_MAX_MS = 30 * 60 * 1000
const CAPTURE_MAX_AGE_MS = 24 * 60 * 60 * 1000

export class WorkflowConversationCaptureService {
    constructor(
        private teamManager: TeamManager,
        private jwt: ScopedServiceJwt,
        private internalApiBaseUrl: string
    ) {}

    get enabled(): boolean {
        return this.jwt.enabled
    }

    async recordSkipped(
        teamId: number,
        invocationId: string,
        reason: 'body_unavailable' | 'queue_unavailable' | 'unmatched_after_send' | 'disabled_after_send'
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
