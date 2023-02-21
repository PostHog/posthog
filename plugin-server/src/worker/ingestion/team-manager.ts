import { Properties } from '@posthog/plugin-scaffold'
import { StatsD } from 'hot-shots'
import LRU from 'lru-cache'

import { ONE_MINUTE } from '../../config/constants'
import { PluginsServerConfig, Team, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { posthog } from '../../utils/posthog'

export class TeamManager {
    db: DB
    teamCache: LRU<TeamId, Team | null>
    tokenToTeamIdCache: LRU<string, TeamId | null>
    statsd?: StatsD
    instanceSiteUrl: string

    constructor(db: DB, serverConfig: PluginsServerConfig, statsd?: StatsD) {
        this.db = db
        this.statsd = statsd

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

    public async fetchTeam(teamId: number): Promise<Team | null> {
        const cachedTeam = this.teamCache.get(teamId)
        if (cachedTeam !== undefined) {
            return cachedTeam
        }

        const timeout = timeoutGuard(`Still running "fetchTeam". Timeout warning after 30 sec!`)
        try {
            const team: Team | null = await this.db.fetchTeam(teamId)
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
         * to failures. If PG is unavailable, this function will trow and the
         * lookup must be retried later.
         *
         * Returns null if the token is invalid.
         */

        const cachedTeamId = this.tokenToTeamIdCache.get(token)

        // Negative lookups (`null` instead of `undefined`) return fast,
        // but will be retried after that cache key expires.
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
            const team = await this.db.fetchTeamByToken(token)
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
            await this.db.postgresQuery(
                `UPDATE posthog_team SET ingested_event = $1 WHERE id = $2`,
                [true, team.id],
                'setTeamIngestedEvent'
            )

            // First event for the team captured
            const organizationMembers = await this.db.postgresQuery(
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
