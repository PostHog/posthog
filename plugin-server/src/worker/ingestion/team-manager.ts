import { Properties } from '@posthog/plugin-scaffold'
import LRU from 'lru-cache'

import { ONE_MINUTE } from '../../config/constants'
import { TeamIDWithConfig } from '../../main/ingestion-queues/session-recording/session-recordings-consumer'
import { PipelineEvent, PluginsServerConfig, Team, TeamId } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { timeoutGuard } from '../../utils/db/utils'
import { posthog } from '../../utils/posthog'

export class TeamManager {
    postgres: PostgresRouter
    teamCache: LRU<TeamId, Team | null>
    tokenToTeamIdCache: LRU<string, TeamId | null>
    instanceSiteUrl: string

    constructor(postgres: PostgresRouter, serverConfig: PluginsServerConfig) {
        this.postgres = postgres

        this.teamCache = new LRU({
            max: 10_000,
            maxAge: 2 * ONE_MINUTE,
            updateAgeOnGet: false, // Make default behaviour explicit
        })
        this.tokenToTeamIdCache = new LRU({
            max: 1_000_000, // Entries are small, keep a high limit to reduce risk of bad requests evicting good tokens
            maxAge: 5 * ONE_MINUTE, // Expiration for negative lookups, positive lookups will expire via teamCache first
            updateAgeOnGet: false, // Make default behaviour explicit
        })
        this.instanceSiteUrl = serverConfig.SITE_URL || 'unknown'
    }

    public async getTeamForEvent(event: PipelineEvent): Promise<Team | null> {
        if (event.team_id) {
            return this.fetchTeam(event.team_id)
        } else if (event.token) {
            return this.getTeamByToken(event.token)
        } else {
            return Promise.resolve(null)
        }
    }

    public async fetchTeam(teamId: number): Promise<Team | null> {
        const cachedTeam = this.teamCache.get(teamId)
        if (cachedTeam !== undefined) {
            return cachedTeam
        }

        const timeout = timeoutGuard(`Still running "fetchTeam". Timeout warning after 30 sec!`)
        try {
            const team: Team | null = await fetchTeam(this.postgres, teamId)
            this.teamCache.set(teamId, team)
            return team
        } finally {
            clearTimeout(timeout)
        }
    }

    public async getTeamByToken(token: string): Promise<Team | null> {
        /**
         * Validates and resolves the api token from an incoming event.
         *
         * Caching is added to reduce the load on Postgres, not to be resilient
         * to failures. If PG is unavailable and the cache expired, this function
         * will trow and the lookup must be retried later.
         *
         * Returns null if the token is invalid.
         */

        const cachedTeamId = this.tokenToTeamIdCache.get(token)

        // LRU.get returns `undefined` if the key is not found, so `null`s will
        // only be returned when caching a negative lookup (invalid token).
        // A new token can potentially get caught here for up to 5 minutes
        // if a bad request in the past used that token.
        if (cachedTeamId === null) {
            return null
        }

        // Positive lookups hit both tokenToTeamIdCache and teamCache before returning without PG lookup.
        // A revoked token will still be accepted until the teamCache entry expires (up to 2 minutes)
        if (cachedTeamId) {
            const cachedTeam = this.teamCache.get(cachedTeamId)
            if (cachedTeam) {
                return cachedTeam
            }
        }

        // Query PG if token is not in cache. This will throw if PG is unavailable.
        const timeout = timeoutGuard(`Still running "fetchTeamByToken". Timeout warning after 30 sec!`)
        try {
            const team = await fetchTeamByToken(this.postgres, token)
            if (!team) {
                // Cache `null` for unknown tokens to reduce PG load, cache TTL will lead to retries later.
                this.tokenToTeamIdCache.set(token, null)
                return null
            }

            this.tokenToTeamIdCache.set(token, team.id)
            this.teamCache.set(team.id, team)
            return team
        } finally {
            clearTimeout(timeout)
        }
    }

    public async setTeamIngestedEvent(team: Team, properties: Properties) {
        if (team && !team.ingested_event) {
            await this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team SET ingested_event = $1 WHERE id = $2`,
                [true, team.id],
                'setTeamIngestedEvent'
            )

            // So long as team id is used as the partition key, this helps avoid
            // double-firing of the first events, but it's not perfect (pod crashes
            // or other rebalances, for example, can still cause double-firing). Exactly
            // once is hard.
            this.teamCache.set(team.id, { ...team, ingested_event: true })

            // First event for the team captured - we fire this because comms and others rely on this event for onboarding flows in downstream systems (e.g. customer.io)
            const organizationMembers = await this.postgres.query(
                PostgresUse.COMMON_WRITE,
                'SELECT distinct_id FROM posthog_user JOIN posthog_organizationmembership ON posthog_user.id = posthog_organizationmembership.user_id WHERE organization_id = $1',
                [team.organization_id],
                'posthog_organizationmembership'
            )
            const distinctIds: { distinct_id: string }[] = organizationMembers.rows
            for (const { distinct_id } of distinctIds) {
                posthog.capture({
                    distinctId: distinct_id,
                    event: 'first team event ingested',
                    properties: {
                        team: team.uuid,
                        sdk: properties.$lib,
                        realm: properties.realm,
                        host: properties.$host,
                    },
                    groups: {
                        project: team.uuid,
                        organization: team.organization_id,
                        instance: this.instanceSiteUrl,
                    },
                })
            }
        }
    }
}

export async function fetchTeam(client: PostgresRouter, teamId: Team['id']): Promise<Team | null> {
    const selectResult = await client.query<Team>(
        PostgresUse.COMMON_READ,
        `
            SELECT
                id,
                uuid,
                organization_id,
                name,
                anonymize_ips,
                api_token,
                slack_incoming_webhook,
                session_recording_opt_in,
                heatmaps_opt_in,
                ingested_event,
                person_display_name_properties,
                test_account_filters
            FROM posthog_team
            WHERE id = $1
            `,
        [teamId],
        'fetchTeam'
    )
    return selectResult.rows[0] ?? null
}

export async function fetchTeamByToken(client: PostgresRouter, token: string): Promise<Team | null> {
    const selectResult = await client.query<Team>(
        PostgresUse.COMMON_READ,
        `
            SELECT
                id,
                uuid,
                organization_id,
                name,
                anonymize_ips,
                api_token,
                slack_incoming_webhook,
                session_recording_opt_in,
                heatmaps_opt_in,
                ingested_event,
                test_account_filters
            FROM posthog_team
            WHERE api_token = $1
            LIMIT 1
                `,
        [token],
        'fetchTeamByToken'
    )
    return selectResult.rows[0] ?? null
}

export async function fetchTeamTokensWithRecordings(client: PostgresRouter): Promise<Record<string, TeamIDWithConfig>> {
    const selectResult = await client.query<{ capture_console_log_opt_in: boolean } & Pick<Team, 'id' | 'api_token'>>(
        PostgresUse.COMMON_READ,
        `
            SELECT id, api_token, capture_console_log_opt_in
            FROM posthog_team
            WHERE session_recording_opt_in = true
        `,
        [],
        'fetchTeamTokensWithRecordings'
    )

    return selectResult.rows.reduce((acc, row) => {
        acc[row.api_token] = { teamId: row.id, consoleLogIngestionEnabled: row.capture_console_log_opt_in }
        return acc
    }, {} as Record<string, TeamIDWithConfig>)
}
