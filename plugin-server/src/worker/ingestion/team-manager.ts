import { Properties } from '@posthog/plugin-scaffold'

import { Team, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { posthog } from '../../utils/posthog'
import { getByAge, UUIDT } from '../../utils/utils'

type TeamCache<T> = Map<TeamId, [T, number]>

export class TeamManager {
    db: DB
    teamCache: TeamCache<Team | null>
    eventNamesCache: Map<TeamId, Set<string>>
    eventPropertiesCache: Map<TeamId, Set<string>>

    constructor(db: DB) {
        this.db = db
        this.teamCache = new Map()
        this.eventNamesCache = new Map()
        this.eventPropertiesCache = new Map()
    }

    public async fetchTeam(teamId: number): Promise<Team | null> {
        const cachedTeam = getByAge(this.teamCache, teamId)
        if (cachedTeam) {
            return cachedTeam
        }

        const timeout = timeoutGuard(`Still running "fetchTeam". Timeout warning after 30 sec!`)
        try {
            const team: Team | null = (await this.db.fetchTeam(teamId)) || null
            this.teamCache.set(teamId, [team, Date.now()])
            return team
        } finally {
            clearTimeout(timeout)
        }
    }

    public async updateEventNamesAndProperties(teamId: number, event: string, properties: Properties): Promise<void> {
        const team: Team | null = await this.fetchTeam(teamId)

        if (!team) {
            return
        }

        const timeout = timeoutGuard('Still running "updateEventNamesAndProperties". Timeout warning after 30 sec!', {
            event: event,
            ingested: team.ingested_event,
        })

        await this.cacheEventNamesAndProperties(team.id)

        if (!this.eventNamesCache.get(team.id)?.has(event)) {
            await this.db.postgresQuery(
                `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, NULL, NULL, $3) ON CONFLICT DO NOTHING`,
                [new UUIDT().toString(), event, team.id],
                'insertEventDefinition'
            )
            this.eventNamesCache.get(team.id)?.add(event)
        }

        for (const [key, value] of Object.entries(properties)) {
            if (!this.eventPropertiesCache.get(team.id)?.has(key)) {
                await this.db.postgresQuery(
                    `INSERT INTO posthog_propertydefinition (id, name, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, NULL, NULL, $4) ON CONFLICT DO NOTHING`,
                    [new UUIDT().toString(), key, typeof value === 'number', team.id],
                    'insertPropertyDefinition'
                )
                this.eventPropertiesCache.get(team.id)?.add(key)
            }
        }

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
                posthog.identify(distinct_id)
                posthog.capture('first team event ingested', {
                    team: team.uuid,
                    sdk: properties.$lib,
                    realm: properties.realm,
                    host: properties.$host,
                })
            }
        }
        clearTimeout(timeout)
    }

    public async cacheEventNamesAndProperties(teamId: number): Promise<void> {
        let eventNamesCache = this.eventNamesCache.get(teamId)
        if (!eventNamesCache) {
            const eventNames = await this.db.postgresQuery(
                'SELECT name FROM posthog_eventdefinition WHERE team_id = $1',
                [teamId],
                'fetchEventDefinitions'
            )
            eventNamesCache = new Set(eventNames.rows.map((r) => r.name))
            this.eventNamesCache.set(teamId, eventNamesCache)
        }

        let eventPropertiesCache = this.eventPropertiesCache.get(teamId)
        if (!eventPropertiesCache) {
            const eventProperties = await this.db.postgresQuery(
                'SELECT name FROM posthog_propertydefinition WHERE team_id = $1',
                [teamId],
                'fetchPropertyDefinitions'
            )
            eventPropertiesCache = new Set(eventProperties.rows.map((r) => r.name))
            this.eventPropertiesCache.set(teamId, eventPropertiesCache)
        }
    }
}
