import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { MinimalAppMetric } from '../../../types'

export type SandboxTerminalOutcome = 'accepted' | 'skipped' | 'failed'

export type SandboxEventProperties = {
    workflow_id: string
    action_id: string
    is_test: boolean
    reason?: string
}

const EVENT_NAMES: Record<SandboxTerminalOutcome, string> = {
    accepted: 'workflows sandbox email sent',
    skipped: 'workflows sandbox email blocked',
    failed: 'workflows sandbox email failed',
}

const METRIC_NAMES: Record<SandboxTerminalOutcome, MinimalAppMetric['metric_name']> = {
    accepted: 'email_sandbox_sent',
    skipped: 'email_sandbox_blocked',
    failed: 'email_sandbox_failed',
}

export function sandboxAppMetric(
    outcome: SandboxTerminalOutcome,
    { teamId, appSourceId, actionId }: { teamId: number; appSourceId: string; actionId: string }
): MinimalAppMetric {
    return {
        team_id: teamId,
        app_source_id: appSourceId,
        instance_id: actionId,
        metric_kind: 'email',
        metric_name: METRIC_NAMES[outcome],
        count: 1,
    }
}

export class SandboxEmailEvents {
    constructor(private readonly teamManager: Pick<TeamManager, 'getTeam'>) {}

    async capture(teamId: number, outcome: SandboxTerminalOutcome, properties: SandboxEventProperties): Promise<void> {
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (team) {
                captureTeamEvent(team, EVENT_NAMES[outcome], properties)
            }
        } catch (error) {
            logger.warn('Could not capture a sandbox email event', { teamId, error: String(error) })
        }
    }
}
