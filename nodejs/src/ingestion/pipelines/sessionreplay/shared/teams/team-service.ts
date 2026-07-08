import { BackgroundRefresher } from '~/common/utils/background-refresher'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { RetentionPeriod, isValidRetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { Team, TeamId } from '~/types'

import { firstPartyHostPatterns } from './first-party-hosts'
import { TeamServiceMetrics } from './metrics'
import { TeamForReplay } from './types'

interface TeamServiceData {
    tokenMap: Record<string, TeamForReplay>
    // The raw DB value; validated to a RetentionPeriod on read in getRetentionPeriodByTeamId.
    retentionMap: Record<TeamId, string>
}

export class TeamService {
    private readonly teamRefresher: BackgroundRefresher<TeamServiceData>

    constructor(private postgres: PostgresRouter) {
        this.teamRefresher = new BackgroundRefresher(
            () => this.fetchTeamTokensWithRecordings(),
            5 * 60 * 1000, // 5 minutes
            (e) => {
                // We ignore the error and wait for postgres to recover
                logger.error('Error refreshing team tokens', e)
                TeamServiceMetrics.incrementRefreshErrors()
            }
        )
    }

    public async getTeamByToken(token: string): Promise<TeamForReplay | null> {
        const { tokenMap } = await this.teamRefresher.get()
        const teamConfig = tokenMap[token]

        if (!teamConfig?.teamId) {
            return null
        }

        return teamConfig
    }

    public async getRetentionPeriodByTeamId(teamId: TeamId): Promise<RetentionPeriod | null> {
        const { retentionMap } = await this.teamRefresher.get()
        const retentionPeriod = retentionMap[teamId]

        if (retentionPeriod === undefined) {
            return null
        }
        if (!isValidRetentionPeriod(retentionPeriod)) {
            // A retention value the DB should never hold — crash rather than record with a wrong
            // (or silently dropped) retention. Thrown without isRetriable so it is not retried into
            // a DLQ but propagates and takes the consumer down.
            throw new Error(`Invalid session_recording_retention_period '${retentionPeriod}' for team ${teamId}`)
        }

        return retentionPeriod
    }

    private async fetchTeamTokensWithRecordings(): Promise<TeamServiceData> {
        return fetchTeamTokensWithRecordings(this.postgres)
    }
}

export async function fetchTeamTokensWithRecordings(client: PostgresRouter): Promise<TeamServiceData> {
    const selectResult = await client.query<
        {
            capture_console_log_opt_in: boolean
            session_recording_retention_period: string
            is_ai_training_opted_in: boolean
            recording_domains: string[] | null
        } & Pick<Team, 'id' | 'api_token'>
    >(
        PostgresUse.COMMON_READ,
        `
            SELECT
                t.id,
                t.api_token,
                t.capture_console_log_opt_in,
                t.session_recording_retention_period,
                t.recording_domains,
                COALESCE(o.is_ai_training_opted_in, false) AS is_ai_training_opted_in
            FROM posthog_team t
            LEFT JOIN posthog_organization o ON o.id = t.organization_id
            WHERE t.session_recording_opt_in = true
        `,
        [],
        'fetchTeamTokensWithRecordings'
    )

    const tokenMap = selectResult.rows.reduce(
        (acc, row) => {
            acc[row.api_token] = {
                teamId: row.id,
                consoleLogIngestionEnabled: row.capture_console_log_opt_in,
                aiTrainingOptedIn: row.is_ai_training_opted_in,
                firstPartyHosts: firstPartyHostPatterns(row.recording_domains),
            }
            return acc
        },
        {} as Record<string, TeamForReplay>
    )

    const retentionMap = selectResult.rows.reduce(
        (acc, row) => {
            acc[row.id] = row.session_recording_retention_period
            return acc
        },
        {} as Record<TeamId, string>
    )

    TeamServiceMetrics.incrementRefreshCount()

    return { tokenMap, retentionMap }
}
