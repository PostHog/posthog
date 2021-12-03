import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Team, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { posthog } from '../../utils/posthog'
import { getByAge, UUIDT } from '../../utils/utils'

type TeamCache<T> = Map<TeamId, [T, number]>

enum EventPropertyType {
    Number = 'NUMBER',
    String = 'STRING',
    Boolean = 'BOOLEAN',
    DateTime = 'DATETIME',
}

export class TeamManager {
    db: DB
    teamCache: TeamCache<Team | null>
    eventDefinitionsCache: Map<TeamId, Set<string>>
    propertyDefinitionsCache: Map<TeamId, Set<string>>
    instanceSiteUrl: string

    constructor(db: DB, instanceSiteUrl?: string | null) {
        this.db = db
        this.teamCache = new Map()
        this.eventDefinitionsCache = new Map()
        this.propertyDefinitionsCache = new Map()
        this.instanceSiteUrl = instanceSiteUrl || 'unknown'
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

    public async updateEventNamesAndProperties(
        teamId: number,
        event: string,
        properties: Properties,
        eventTimestamp: DateTime
    ): Promise<void> {
        const team: Team | null = await this.fetchTeam(teamId)

        if (!team) {
            return
        }

        const timeout = timeoutGuard('Still running "updateEventNamesAndProperties". Timeout warning after 30 sec!', {
            event: event,
            ingested: team.ingested_event,
        })

        await this.cacheEventNamesAndProperties(team.id)

        if (!this.eventDefinitionsCache.get(team.id)?.has(event)) {
            await this.db.postgresQuery(
                `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, NULL, NULL, $3) ON CONFLICT DO NOTHING`,
                [new UUIDT().toString(), event, team.id],
                'insertEventDefinition'
            )
            this.eventDefinitionsCache.get(team.id)?.add(event)
        }

        for (const [key, value] of Object.entries(properties)) {
            if (!this.propertyDefinitionsCache.get(team.id)?.has(key)) {
                await this.db.postgresQuery(
                    `INSERT INTO posthog_propertydefinition (id, name, is_numerical, volume_30_day, query_usage_30_day, team_id) VALUES ($1, $2, $3, NULL, NULL, $4) ON CONFLICT DO NOTHING`,
                    [new UUIDT().toString(), key, typeof value === 'number', team.id],
                    'insertPropertyDefinition'
                )
                this.propertyDefinitionsCache.get(team.id)?.add(key)
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
                    $groups: {
                        project: team.uuid,
                        organization: team.organization_id,
                        instance: this.instanceSiteUrl,
                    },
                })
            }
        }

        await this.updateEventProperties(team, event, properties, eventTimestamp)

        clearTimeout(timeout)
    }

    public async cacheEventNamesAndProperties(teamId: number): Promise<void> {
        let eventDefinitionsCache = this.eventDefinitionsCache.get(teamId)
        if (!eventDefinitionsCache) {
            const eventNames = await this.db.postgresQuery(
                'SELECT name FROM posthog_eventdefinition WHERE team_id = $1',
                [teamId],
                'fetchEventDefinitions'
            )
            eventDefinitionsCache = new Set(eventNames.rows.map((r) => r.name))
            this.eventDefinitionsCache.set(teamId, eventDefinitionsCache)
        }

        let propertyDefinitionsCache = this.propertyDefinitionsCache.get(teamId)
        if (!propertyDefinitionsCache) {
            const eventProperties = await this.db.postgresQuery(
                'SELECT name FROM posthog_propertydefinition WHERE team_id = $1',
                [teamId],
                'fetchPropertyDefinitions'
            )
            propertyDefinitionsCache = new Set(eventProperties.rows.map((r) => r.name))
            this.propertyDefinitionsCache.set(teamId, propertyDefinitionsCache)
        }
    }

    public async updateEventProperties(
        team: Team,
        event: string,
        properties: Record<string, any>,
        eventTimestamp: DateTime
    ): Promise<void> {
        await this.db.postgresTransaction(async (client) => {
            for (const [property, value] of Object.entries(properties)) {
                let propertyType =
                    typeof value === 'number'
                        ? EventPropertyType.Number
                        : typeof value === 'boolean'
                        ? EventPropertyType.Boolean
                        : typeof value === 'string'
                        ? EventPropertyType.String
                        : null
                let propertyTypeFormat = null

                if (propertyType === EventPropertyType.String) {
                    const dateFormat = detectDateFormat(value)
                    if (dateFormat) {
                        propertyType = EventPropertyType.DateTime
                        propertyTypeFormat = dateFormat
                    }
                }

                const totalVolume = 1

                // starting with a naive implementation
                await client.query(
                    'INSERT INTO posthog_eventproperty (team_id, event, property, property_type, property_type_format, total_volume, created_at, last_seen_at) ' +
                        'VALUES ($1, $2, $3, $4, $5, $6, NOW(), $7) ON CONFLICT ON CONSTRAINT posthog_eventproperty_team_id_event_property_10910b3b_uniq DO UPDATE SET ' +
                        'total_volume = posthog_eventproperty.total_volume+$6, ' +
                        'last_seen_at = GREATEST(posthog_eventproperty.last_seen_at, $7), ' +
                        'property_type = CASE WHEN posthog_eventproperty.property_type IS NULL THEN $4 ELSE posthog_eventproperty.property_type END, ' +
                        'property_type_format = CASE WHEN posthog_eventproperty.property_type_format IS NULL THEN $5 ELSE posthog_eventproperty.property_type_format END, ',
                    [team.id, event, property, propertyType, propertyTypeFormat, totalVolume, eventTimestamp]
                )
            }
        })
    }
}

function detectDateFormat(value: string): string | void {
    if (value.match(/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/)) {
        return 'YYYY-MM-DD'
    }
}
