import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'

export type TeamWorkflowsConfig = {
    capture_workflows_engagement_events: boolean
}

const DEFAULT_CONFIG: TeamWorkflowsConfig = {
    capture_workflows_engagement_events: false,
}

/**
 * Reads `workflows_teamworkflowsconfig` rows. The Django side creates a row
 * lazily via `get_or_create_team_extension`, so a missing row means the team
 * has never opted in — return the default (engagement event capture off).
 */
export class TeamWorkflowsConfigService {
    private lazyLoader: LazyLoader<TeamWorkflowsConfig>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'team_workflows_config',
            refreshAgeMs: 2 * 60 * 1000,
            refreshJitterMs: 30 * 1000,
            loader: async (teamIds) => await this.fetchConfigs(teamIds),
        })
    }

    public async get(teamId: number): Promise<TeamWorkflowsConfig> {
        return (await this.lazyLoader.get(String(teamId))) ?? DEFAULT_CONFIG
    }

    public async shouldCaptureEngagementEvents(teamId: number): Promise<boolean> {
        const config = await this.get(teamId)
        return config.capture_workflows_engagement_events
    }

    private async fetchConfigs(teamIds: string[]): Promise<Record<string, TeamWorkflowsConfig>> {
        const result = await this.postgres.query<{ team_id: number; capture_workflows_engagement_events: boolean }>(
            PostgresUse.COMMON_READ,
            `SELECT team_id, capture_workflows_engagement_events
             FROM workflows_teamworkflowsconfig
             WHERE team_id = ANY($1)`,
            [teamIds.map(Number)],
            'fetch-team-workflows-configs'
        )

        const configs: Record<string, TeamWorkflowsConfig> = {}
        for (const teamId of teamIds) {
            configs[teamId] = DEFAULT_CONFIG
        }
        for (const row of result.rows) {
            configs[String(row.team_id)] = {
                capture_workflows_engagement_events: row.capture_workflows_engagement_events,
            }
        }
        return configs
    }
}
