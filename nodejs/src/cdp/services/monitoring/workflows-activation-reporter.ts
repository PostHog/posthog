import { LRUCache } from 'lru-cache'

import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { Team } from '~/types'

type WorkflowsActivationEvents = {
    'workflows message delivered': { workflow_id: string; channel: 'email' }
    'workflows send blocked': { workflow_id: string; channel: 'email'; reason: 'quota_limited' }
    'workflows send failed': {
        workflow_id: string
        channel: 'email'
        reason: 'unverified_domain' | 'missing_recipient'
    }
}

const REPORT_INTERVAL_MS = 60 * 60 * 1000

export class WorkflowsActivationReporter {
    private lastReportedAt = new LRUCache<string, number>({ max: 50_000 })

    constructor(
        private teamManager: { getTeam(teamId: number): Promise<Team | null> },
        private capture: typeof captureTeamEvent = captureTeamEvent
    ) {}

    public async report<Event extends keyof WorkflowsActivationEvents>(
        teamId: number,
        event: Event,
        properties: WorkflowsActivationEvents[Event]
    ): Promise<void> {
        const reason = 'reason' in properties ? properties.reason : ''
        const key = `${teamId}:${event}:${reason}`
        const now = Date.now()
        const lastReportedAt = this.lastReportedAt.get(key)
        if (lastReportedAt !== undefined && now - lastReportedAt < REPORT_INTERVAL_MS) {
            return
        }
        this.lastReportedAt.set(key, now)

        try {
            const team = await this.teamManager.getTeam(teamId)
            if (!team) {
                this.lastReportedAt.delete(key)
                return
            }
            this.capture(team, event, properties)
        } catch (error) {
            this.lastReportedAt.delete(key)
            logger.warn('Failed to report a workflows activation event', { teamId, event, error })
        }
    }
}
