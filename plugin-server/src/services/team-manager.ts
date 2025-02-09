import { Properties } from '@posthog/plugin-scaffold'
import LRU from 'lru-cache'

import { Config, ProjectId, Team, TeamId, TeamIDWithConfig } from '../types'
import { PostgresRouter, PostgresUse } from '../utils/postgres'
import { posthog } from '../utils/posthog'

export const ONE_MINUTE = 60 * 1000

export class TeamManager {
    teamCache: LRU<TeamId, Team | null>
    tokenToTeamIdCache: LRU<string, TeamId | null>

    constructor(private postgres: PostgresRouter, private serverConfig: Config) {
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
    }

    // NOTE: We purposefully don't offer helper methods to get individual teams
    // because we want to force callers to fetch all necessary teams at once to avoid parallel PG requests
    public async getTeams(
        tokens: string[] = [],
        ids: number[] = []
    ): Promise<{
        byToken: Record<string, Team | null>
        byId: Record<number, Team | null>
    }> {
        // Highly optimized method for loading teams by token and/or id
        // Returns a pair of maps, one by token and the other by id
        // If possible returns from the cache, otherwise fetches from PG

        const teamsById: Record<number, Team | null> = {}
        const teamsByToken: Record<string, Team | null> = {}

        const tokensToFetch = new Set<string>()
        const teamIdsToFetch = new Set<number>()

        for (const token of tokens) {
            const teamId = this.tokenToTeamIdCache.get(token)
            const team = teamId ? this.teamCache.get(teamId) : undefined
            if (team || team === null) {
                // If it is null or defined then we return it (we don't need to lookup again)
                teamsByToken[token] = team
            } else {
                tokensToFetch.add(token)
            }
        }

        for (const id of ids) {
            const team = this.teamCache.get(id)
            if (team || team === null) {
                // If it is null or defined then we return it (we don't need to lookup again)
                teamsById[id] = team
            } else {
                teamIdsToFetch.add(id)
            }
        }

        if (!tokensToFetch.size && !teamIdsToFetch.size) {
            return { byToken: teamsByToken, byId: teamsById }
        }

        let fetchedTeams: Team[] = []

        const BASE_QUERY = `SELECT
                id,
                project_id,
                uuid,
                organization_id,
                name,
                anonymize_ips,
                api_token,
                slack_incoming_webhook,
                session_recording_opt_in,
                person_processing_opt_out,
                heatmaps_opt_in,
                ingested_event,
                person_display_name_properties,
                test_account_filters,
                cookieless_server_hash_mode,
                timezone
            FROM posthog_team`

        // TODO: Also get the org info

        if (tokensToFetch.size) {
            // Fetch only the teams we don't have in the cache
            const selectResult = await this.postgres.query<Team>(
                PostgresUse.COMMON_READ,
                `${BASE_QUERY} WHERE api_token = ANY($1)`,
                [Array.from(tokensToFetch)],
                'fetchTeamsByToken'
            )

            fetchedTeams = fetchedTeams.concat(selectResult.rows)
        }

        if (teamIdsToFetch.size) {
            // Fetch only the teams we don't have in the cache
            const selectResult = await this.postgres.query<Team>(
                PostgresUse.COMMON_READ,
                `${BASE_QUERY} WHERE id = ANY($1)`,
                [Array.from(teamIdsToFetch)],
                'fetchTeamsById'
            )

            fetchedTeams = fetchedTeams.concat(selectResult.rows)
        }

        // Add all found teams to our caches and results
        for (const team of fetchedTeams) {
            // pg returns int8 as a string, since it can be larger than JS's max safe integer,
            // but this is not a problem for project_id, which is a long long way from that limit.
            team.project_id = Number(team.project_id) as ProjectId
            this.tokenToTeamIdCache.set(team.api_token, team.id)
            this.teamCache.set(team.id, team)

            teamsByToken[team.api_token] = team
            teamsById[team.id] = team
        }

        // Add nulls for any tokens that were not found
        for (const token of tokensToFetch) {
            if (!teamsByToken[token]) {
                teamsByToken[token] = null
            }
        }
        for (const id of teamIdsToFetch) {
            if (!teamsById[id]) {
                teamsById[id] = null
            }
        }

        return { byToken: teamsByToken, byId: teamsById }
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
                        instance: this.serverConfig.SITE_URL || 'unknown',
                    },
                })
            }
        }
    }
}

// TODO: Move this to the dedicated session recording service

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
