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
            max: 10000,
            maxAge: 2 * ONE_MINUTE,
            // being explicit about the fact that we want to update
            // the team cache every 2min, irrespective of the last access
            updateAgeOnGet: false,
        })
        this.tokenToTeamIdCache = new LRU({
            // TODO: add `maxAge` to ensure we avoid negatively caching teamId as null.
            max: 100_000,
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
        const cachedTeamId = this.tokenToTeamIdCache.get(token)

        // tokenToTeamIdCache.get returns `undefined` if the value doesn't
        // exist so we check for the value being `null` as that means we've
        // explictly cached that the team does not exist
        if (cachedTeamId === null) {
            return null
        } else if (cachedTeamId) {
            const cachedTeam = this.teamCache.get(cachedTeamId)
            if (cachedTeam) {
                return cachedTeam
            }
        }

        const timeout = timeoutGuard(`Still running "fetchTeam". Timeout warning after 30 sec!`)
        try {
            const team = await this.db.fetchTeamByToken(token)
            if (!team) {
                // explicitly cache a null to avoid
                // unnecessary lookups in the future
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
