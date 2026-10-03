import { LRUCache } from 'lru-cache'

import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { Team } from '~/types'

export type WorkflowsActivationEvent =
    | 'workflows message delivered'
    | 'workflows send blocked'
    | 'workflows send failed'

export type WorkflowsActivationProperties = {
    workflow_id: string
    channel?: 'email'
    reason?: 'quota_limited' | 'unverified_domain' | 'missing_recipient'
}

const REPORT_INTERVAL_MS = 60 * 60 * 1000

// One event per send would flood product analytics, and a funnel only needs the first occurrence.
export class WorkflowsActivationReporter {
    private lastReportedAt = new LRUCache<string, number>({ max: 50_000 })

    constructor(
        private teamManager: { getTeam(teamId: number): Promise<Team | null> },
        private capture: typeof captureTeamEvent = captureTeamEvent
    ) {}

    public async report(
        teamId: number,
        event: WorkflowsActivationEvent,
        properties: WorkflowsActivationProperties
    ): Promise<void> {
        const key = `${teamId}:${event}:${properties.reason ?? ''}`
        const now = Date.now()
        const lastReportedAt = this.lastReportedAt.get(key)
        if (lastReportedAt !== undefined && now - lastReportedAt < REPORT_INTERVAL_MS) {
            return
        }
        this.lastReportedAt.set(key, now)

        try {
            const team = await this.teamManager.getTeam(teamId)
            if (team) {
                this.capture(team, event, properties)
            }
        } catch (error) {
            logger.warn('Failed to report a workflows activation event', { teamId, event, error })
        }
    }
}
