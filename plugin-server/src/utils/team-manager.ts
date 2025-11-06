import { Properties } from '@posthog/plugin-scaffold'

import { OrganizationAvailableFeature, ProjectId, Team } from '../types'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'
import { captureTeamEvent } from './posthog'

type RawTeam = Omit<Team, 'availableFeatures'> & {
    available_product_features: { key: string; name: string }[]
}

export class TeamManager {
    private lazyLoader: LazyLoader<Team>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'TeamManager',
            refreshAgeMs: 2 * 60 * 1000, // 2 minute
            refreshJitterMs: 30 * 1000, // 30 seconds
            loader: async (teamIdOrTokens: string[]) => {
                return await this.fetchTeams(teamIdOrTokens)
            },
        })
    }

    public async getTeam(teamId: number): Promise<Team | null> {
        return this.lazyLoader.get(String(teamId))
    }

    public async getTeamByToken(token: string): Promise<Team | null> {
        return this.lazyLoader.get(token)
    }

    public async getTeams(teamIds: number[]): Promise<Record<string, Team | null>> {
        return this.lazyLoader.getMany(teamIds.map(String))
    }

    public async getTeamsByTokens(tokens: string[]): Promise<Record<string, Team | null>> {
        return this.lazyLoader.getMany(tokens)
    }

    public async hasAvailableFeature(teamId: number, feature: OrganizationAvailableFeature): Promise<boolean> {
        const team = await this.getTeam(teamId)
        return team?.available_features.includes(feature) || false
    }

    public async setTeamIngestedEvent(team: Team, properties: Properties): Promise<void> {
        if (!team.ingested_event) {
            await this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team SET ingested_event = $1 WHERE id = $2`,
                [true, team.id],
                'setTeamIngestedEvent'
            )

            // Invalidate the cache for this team
            this.lazyLoader.markForRefresh(String(team.id))

            const organizationMembers = await this.postgres.query(
                PostgresUse.COMMON_WRITE,
                'SELECT distinct_id FROM posthog_user JOIN posthog_organizationmembership ON posthog_user.id = posthog_organizationmembership.user_id WHERE organization_id = $1',
                [team.organization_id],
                'posthog_organizationmembership'
            )

            const distinctIds: { distinct_id: string }[] = organizationMembers.rows
            for (const { distinct_id } of distinctIds) {
                captureTeamEvent(
                    team,
                    'first team event ingested',
                    {
                        sdk: properties.$lib,
                        realm: properties.realm,
                        host: properties.$host,
                    },
                    distinct_id
                )
            }
        }
    }

    public async getTeamForEvent(event: { team_id?: number | null; token?: string | null }): Promise<Team | null> {
        if (event.team_id) {
            return this.getTeam(event.team_id)
        } else if (event.token) {
            return this.getTeamByToken(event.token)
        }
        return null
    }

    private async fetchTeams(teamIdOrTokens: string[]): Promise<Record<string, Team | null>> {
        const [teamIds, tokens] = teamIdOrTokens.reduce(
            ([teamIds, tokens], idOrToken) => {
                // TRICKY: We are caching ids and tokens so we need to determine which is which
                // Fix this to be a prefix based lookup. Added hack to limit to positive integer
                // that shouldn't overflow 32-bit integer in DB column.
                if (/^\d{1,10}$/.test(idOrToken)) {
                    const parsed = parseInt(idOrToken)
                    // TODO: stat if this happens
                    if (!isNaN(parsed) && parsed > 0 && parsed <= 2147483647) {
                        teamIds.push(parsed)
                    }
                } else {
                    tokens.push(idOrToken)
                }
                return [teamIds, tokens]
            },
            [[] as number[], [] as string[]]
        )

        const result = await this.postgres.query<RawTeam>(
            PostgresUse.COMMON_READ,
            `SELECT
                t.id,
                t.project_id,
                t.uuid,
                t.organization_id,
                t.name,
                t.anonymize_ips,
                t.api_token,
                t.slack_incoming_webhook,
                t.session_recording_opt_in,
                t.person_processing_opt_out,
                t.heatmaps_opt_in,
                t.ingested_event,
                t.person_display_name_properties,
                t.cookieless_server_hash_mode,
                t.timezone,
                t.verify_events,
                extract('epoch' from t.drop_events_older_than) as drop_events_older_than_seconds,
                o.available_product_features
            FROM posthog_team t
            JOIN posthog_organization o ON o.id = t.organization_id
            WHERE t.id = ANY($1) OR t.api_token = ANY($2)
            `,
            [teamIds, tokens],
            'fetch-teams-with-features'
        )

        // Initialize result record with nulls for all requested IDs/tokens
        const resultRecord: Record<string, Team | null> = {}
        for (const idOrToken of teamIdOrTokens) {
            resultRecord[idOrToken] = null
        }

        // Fill in actual teams where they exist
        result.rows.forEach((row) => {
            const { available_product_features, ...teamPartial } = row
            const team: Team = {
                ...teamPartial,
                // NOTE: The postgres lib loads the bigint as a string, so we need to cast it to a ProjectId
                project_id: Number(teamPartial.project_id) as ProjectId,
                available_features: available_product_features?.map((f) => f.key as OrganizationAvailableFeature) || [],
            }
            resultRecord[row.id] = team
            resultRecord[row.api_token] = team
        })

        return resultRecord as Record<string, Team | null>
    }
}
