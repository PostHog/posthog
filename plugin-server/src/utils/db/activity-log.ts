import { Hub, Team, TeamId } from '../../types'
import { logger } from '../logger'
import { UUIDT } from '../utils'
import { PostgresUse } from './postgres'

interface Trigger {
    job_type: string
    job_id: string
    payload: Record<string, any>
}

export async function createPluginActivityLog(
    hub: Hub,
    team: TeamId | Team,
    pluginConfigId: number,
    activity: string,
    details: { trigger: Trigger }
) {
    const teamObject: Team | null = typeof team === 'number' ? await hub.teamManager.getTeam(team) : team
    if (!teamObject) {
        logger.warn('🤔', `Could not find team ${team} to create an activity log for. Skipping.`)
        return
    }

    await hub.db.postgres.query(
        PostgresUse.COMMON_WRITE,
        `
        INSERT INTO posthog_activitylog (id, team_id, organization_id, activity, item_id, detail, scope, is_system, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, 'PluginConfig', TRUE, NOW())
        `,
        [new UUIDT().toString(), teamObject.id, teamObject.organization_id, activity, pluginConfigId, details],
        'createPluginActivityLog'
    )
}
