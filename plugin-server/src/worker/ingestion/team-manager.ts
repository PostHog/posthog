import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { defaultConfig } from '../../config/config'
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
    eventLastSeenCache: Map<string, number> // key: ${team_id}_${name}; value: DateTime.valueOf()
    lastFlushAt: DateTime // time when the `eventLastSeenCache` was last flushed
    eventPropertiesCache: Map<TeamId, Set<string>>
    instanceSiteUrl: string
    experimentalLastSeenAtEnabledTeams: string[]

    // TODO: #7422 Remove temporary parameter
    constructor(db: DB, instanceSiteUrl?: string | null, experimentalLastSeenAtEnabledTeams?: string) {
        this.db = db
        this.teamCache = new Map()
        this.eventNamesCache = new Map()
        this.eventLastSeenCache = new Map()
        this.eventPropertiesCache = new Map()
        this.instanceSiteUrl = instanceSiteUrl || 'unknown'
        this.lastFlushAt = DateTime.now()
        this.experimentalLastSeenAtEnabledTeams = experimentalLastSeenAtEnabledTeams?.split(',') ?? []
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

    async flushLastSeenAtCache(): Promise<void> {
        let valuesStatement = ''
        let params: (string | number)[] = []

        const events = this.eventLastSeenCache
        this.eventLastSeenCache = new Map()

        for (const event of events) {
            const [key, value] = event
            const [teamId, eventName] = JSON.parse(key)
            if (teamId && eventName && value) {
                valuesStatement += `($${params.length + 1}, $${params.length + 2}, $${params.length + 3}),`
                params = params.concat([teamId, eventName, value])
            }
        }

        this.lastFlushAt = DateTime.now()

        if (params.length) {
            await this.db.postgresQuery(
                `UPDATE posthog_eventdefinition AS t1 SET last_seen_at = GREATEST(t1.last_seen_at, to_timestamp(t2.last_seen_at::integer))
                FROM (VALUES ${valuesStatement.substring(
                    0,
                    valuesStatement.length - 1
                )}) AS t2(team_id, name, last_seen_at)
                WHERE t1.name = t2.name AND t1.team_id = t2.team_id::integer`,
                [...params],
                'updateEventLastSeen'
            )
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

        if (!this.eventNamesCache.get(team.id)?.has(event)) {
            // TODO: #7422 Temporary conditional to test experimental feature
            if (this.experimentalLastSeenAtEnabledTeams.includes(team.id.toString())) {
                await this.db.postgresQuery(
                    `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, last_seen_at, created_at)` +
                        ` VALUES ($1, $2, NULL, NULL, $3, $4, NOW())` +
                        ` ON CONFLICT ON CONSTRAINT posthog_eventdefinition_team_id_name_80fa0b87_uniq` +
                        ` DO UPDATE SET last_seen_at=$4`,
                    [new UUIDT().toString(), event, team.id, eventTimestamp],
                    'insertEventDefinition'
                )
            } else {
                await this.db.postgresQuery(
                    `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, created_at)` +
                        ` VALUES ($1, $2, NULL, NULL, $3, NOW())` +
                        ` ON CONFLICT DO NOTHING`,
                    [new UUIDT().toString(), event, team.id],
                    'insertEventDefinition'
                )
            }
            this.eventNamesCache.get(team.id)?.add(event)
        } else {
            // TODO: #7422 Temporary conditional to test experimental feature
            if (this.experimentalLastSeenAtEnabledTeams.includes(team.id.toString())) {
                const eventCacheKey = JSON.stringify([team.id, event])
                if ((this.eventLastSeenCache.get(eventCacheKey) ?? 0) < eventTimestamp.valueOf()) {
                    this.eventLastSeenCache.set(eventCacheKey, eventTimestamp.valueOf())
                }
                if (this.eventLastSeenCache.size > 100000 || DateTime.now().diff(this.lastFlushAt).minutes > 360) {
                    // to not run out of memory
                    await this.flushLastSeenAtCache()
                }
            }
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
                    $groups: {
                        project: team.uuid,
                        organization: team.organization_id,
                        instance: this.instanceSiteUrl,
                    },
                })
            }
        }
        clearTimeout(timeout)
    }

    public async cacheEventNamesAndProperties(teamId: number): Promise<void> {
        let eventNamesCache = this.eventNamesCache.get(teamId)
        if (!eventNamesCache) {
            const eventData = await this.db.postgresQuery(
                'SELECT name FROM posthog_eventdefinition WHERE team_id = $1',
                [teamId],
                'fetchEventDefinitions'
            )
            eventNamesCache = new Set(eventData.rows.map((r) => r.name))
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
