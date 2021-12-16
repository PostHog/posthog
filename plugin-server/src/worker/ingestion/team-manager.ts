import { Properties } from '@posthog/plugin-scaffold'
import { StatsD } from 'hot-shots'
import { DateTime } from 'luxon'

import { Team, TeamId } from '../../types'
import { DB } from '../../utils/db/db'
import { timeoutGuard } from '../../utils/db/utils'
import { posthog } from '../../utils/posthog'
import { status } from '../../utils/status'
import { getByAge, UUIDT } from '../../utils/utils'

type TeamCache<T> = Map<TeamId, [T, number]>

export class TeamManager {
    db: DB
    teamCache: TeamCache<Team | null>
    eventDefinitionsCache: Map<TeamId, Set<string>>
    eventLastSeenCache: Map<string, number> // key: ${team_id}_${name}; value: DateTime.valueOf()
    lastFlushAt: DateTime // time when the `eventLastSeenCache` was last flushed
    propertyDefinitionsCache: Map<TeamId, Set<string>>
    instanceSiteUrl: string
    experimentalLastSeenAtEnabled: boolean
    statsd?: StatsD

    // TODO: #7422 Remove temporary parameter
    constructor(db: DB, statsd?: StatsD, instanceSiteUrl?: string | null, experimentalLastSeenAtEnabled?: boolean) {
        this.db = db
        this.statsd = statsd
        this.teamCache = new Map()
        this.eventDefinitionsCache = new Map()
        this.eventLastSeenCache = new Map()
        this.propertyDefinitionsCache = new Map()
        this.instanceSiteUrl = instanceSiteUrl || 'unknown'
        this.lastFlushAt = DateTime.now()
        this.experimentalLastSeenAtEnabled = experimentalLastSeenAtEnabled ?? false
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
        const valuesStatements = []
        const params: (string | number)[] = []

        const startTime = DateTime.now()
        const cacheSize = this.eventLastSeenCache.size

        const lastFlushedSecondsAgo = DateTime.now().diff(this.lastFlushAt).as('seconds')
        status.info(
            `🚽 Starting flushLastSeenAtCache. Cache size: ${cacheSize} items. Last flushed: ${lastFlushedSecondsAgo} seconds ago.`
        )

        const events = this.eventLastSeenCache
        this.eventLastSeenCache = new Map()

        for (const event of events) {
            const [key, value] = event
            const [teamId, eventName] = JSON.parse(key)
            if (teamId && eventName && value) {
                valuesStatements.push(`($${params.length + 1},$${params.length + 2},$${params.length + 3})`)
                params.push(teamId, eventName, value / 1000)
            }
        }

        this.lastFlushAt = DateTime.now()

        if (params.length) {
            await this.db.postgresQuery(
                `UPDATE posthog_eventdefinition AS t1 SET last_seen_at = GREATEST(t1.last_seen_at, to_timestamp(t2.last_seen_at::numeric))
                FROM (VALUES ${valuesStatements.join(',')}) AS t2(team_id, name, last_seen_at)
                WHERE t1.name = t2.name AND t1.team_id = t2.team_id::integer`,
                params,
                'updateEventLastSeen'
            )
        }
        const elapsedTime = DateTime.now().diff(startTime).as('milliseconds')
        this.statsd?.set('flushLastSeenAtCache.Size', cacheSize)
        this.statsd?.set('flushLastSeenAtCache.QuerySize', params.length)
        this.statsd?.timing('flushLastSeenAtCache', elapsedTime)
        status.info(`✅ 🚽 flushLastSeenAtCache finished successfully in ${elapsedTime} ms.`)
    }

    public async updateEventNamesAndProperties(teamId: number, event: string, properties: Properties): Promise<void> {
        const startTime = DateTime.now()
        const team: Team | null = await this.fetchTeam(teamId)

        if (!team) {
            return
        }

        const timeout = timeoutGuard('Still running "updateEventNamesAndProperties". Timeout warning after 30 sec!', {
            event: event,
            ingested: team.ingested_event,
        })

        await this.cacheEventNamesAndProperties(team.id)
        await this.syncEventDefinitions(team, event)
        await this.syncPropertyDefinitions(properties, team)
        await this.setTeamIngestedEvent(team, properties)

        clearTimeout(timeout)

        const statsDEvent = this.experimentalLastSeenAtEnabled
            ? 'updateEventNamesAndProperties.lastSeenAtEnabled'
            : 'updateEventNamesAndProperties'
        this.statsd?.timing(statsDEvent, DateTime.now().diff(startTime).as('milliseconds'))
    }

    private async syncEventDefinitions(team: Team, event: string) {
        if (!this.eventDefinitionsCache.get(team.id)?.has(event)) {
            // TODO: #7422 Temporary conditional to test experimental feature
            if (this.experimentalLastSeenAtEnabled) {
                status.info('Inserting new event definition with last_seen_at')
                await this.db.postgresQuery(
                    `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, last_seen_at, created_at)` +
                        ` VALUES ($1, $2, NULL, NULL, $3, NOW(), NOW())` +
                        ` ON CONFLICT ON CONSTRAINT posthog_eventdefinition_team_id_name_80fa0b87_uniq` +
                        ` DO UPDATE SET last_seen_at=NOW()`,
                    [new UUIDT().toString(), event, team.id],
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
            this.eventDefinitionsCache.get(team.id)?.add(event)
        } else {
            // TODO: #7422 Temporary conditional to test experimental feature
            if (this.experimentalLastSeenAtEnabled) {
                const eventCacheKey = JSON.stringify([team.id, event])
                if ((this.eventLastSeenCache.get(eventCacheKey) ?? 0) < DateTime.now().valueOf()) {
                    this.eventLastSeenCache.set(eventCacheKey, DateTime.now().valueOf())
                }
                // TODO: Allow configuring this via env vars
                // We flush here every 2 mins (as a failsafe) because the main thread flushes every minute
                if (this.eventLastSeenCache.size > 1000 || DateTime.now().diff(this.lastFlushAt).as('seconds') > 120) {
                    // to not run out of memory
                    await this.flushLastSeenAtCache()
                }
            }
        }
    }

    private async syncPropertyDefinitions(properties: Properties, team: Team) {
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
    }

    private async setTeamIngestedEvent(team: Team, properties: Properties) {
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
}
