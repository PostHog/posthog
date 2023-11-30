import { Properties } from '@posthog/plugin-scaffold'
import { StatsD } from 'hot-shots'
import LRU from 'lru-cache'
import { DateTime } from 'luxon'
import { Summary } from 'prom-client'

import { ONE_HOUR } from '../../config/constants'
import {
    GroupTypeIndex,
    PluginsServerConfig,
    PropertyDefinitionTypeEnum,
    PropertyType,
    Team,
    TeamId,
} from '../../types'
import { DB } from '../../utils/db/db'
import { PostgresUse } from '../../utils/db/postgres'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { UUIDT } from '../../utils/utils'
import { GroupTypeManager } from './group-type-manager'
import { detectPropertyDefinitionTypes } from './property-definitions-auto-discovery'
import { PropertyDefinitionsCache } from './property-definitions-cache'
import { TeamManager } from './team-manager'

// for e.g. internal events we don't want to be available for users in the UI
const EVENTS_WITHOUT_EVENT_DEFINITION = ['$$plugin_metrics']
// These are used internally for manipulating person/group properties
const NOT_SYNCED_PROPERTIES = new Set([
    '$set',
    '$set_once',
    '$unset',
    '$group_0',
    '$group_1',
    '$group_2',
    '$group_3',
    '$group_4',
    '$groups',
])

const updateEventNamesAndPropertiesMsSummary = new Summary({
    name: 'update_event_names_and_properties_ms',
    help: 'Duration spent in updateEventNamesAndProperties',
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

type PartialPropertyDefinition = {
    key: string
    type: PropertyDefinitionTypeEnum
    value: any
    groupTypeIndex: GroupTypeIndex | null
}

export class PropertyDefinitionsManager {
    db: DB
    teamManager: TeamManager
    groupTypeManager: GroupTypeManager
    eventDefinitionsCache: LRU<TeamId, Set<string>>
    eventPropertiesCache: LRU<string, Set<string>> // Map<JSON.stringify([TeamId, Event], Set<Property>>
    eventLastSeenCache: LRU<string, number> // key: JSON.stringify([team_id, event]); value: parseInt(YYYYMMDD)
    propertyDefinitionsCache: PropertyDefinitionsCache
    statsd?: StatsD
    private readonly lruCacheSize: number

    constructor(
        teamManager: TeamManager,
        groupTypeManager: GroupTypeManager,
        db: DB,
        serverConfig: PluginsServerConfig,
        statsd?: StatsD
    ) {
        this.db = db
        this.statsd = statsd
        this.teamManager = teamManager
        this.groupTypeManager = groupTypeManager
        this.lruCacheSize = serverConfig.EVENT_PROPERTY_LRU_SIZE

        this.eventDefinitionsCache = new LRU({
            max: this.lruCacheSize,
            maxAge: ONE_HOUR * 24,
            updateAgeOnGet: true,
        })
        this.eventPropertiesCache = new LRU({
            max: this.lruCacheSize, // keep in memory the last 10k team+event combos we have seen
            maxAge: ONE_HOUR * 24, // cache up to 24h
            updateAgeOnGet: true,
        })
        this.eventLastSeenCache = new LRU({
            max: this.lruCacheSize, // keep in memory the last 10k team+event combos we have seen
            maxAge: ONE_HOUR * 24, // cache up to 24h
            updateAgeOnGet: true,
        })
        this.propertyDefinitionsCache = new PropertyDefinitionsCache(serverConfig, statsd)
    }

    public async updateEventNamesAndProperties(teamId: number, event: string, properties: Properties): Promise<void> {
        if (EVENTS_WITHOUT_EVENT_DEFINITION.includes(event)) {
            return
        }

        const timer = new Date()
        const timeout = timeoutGuard('Still running "updateEventNamesAndProperties". Timeout warning after 30 sec!', {
            event: event,
        })

        try {
            const team: Team | null = await this.teamManager.fetchTeam(teamId)

            if (!team) {
                return
            }
            await this.cacheEventNamesAndProperties(team.id, event)
            await Promise.all([
                this.syncEventDefinitions(team, event),
                this.syncEventProperties(team, event, properties),
                this.syncPropertyDefinitions(team, event, properties),
                this.teamManager.setTeamIngestedEvent(team, properties),
            ])
        } finally {
            clearTimeout(timeout)
            this.statsd?.timing('updateEventNamesAndProperties', timer)
            updateEventNamesAndPropertiesMsSummary.observe(Date.now() - timer.valueOf())
        }
    }

    private async syncEventDefinitions(team: Team, event: string) {
        const cacheKey = JSON.stringify([team.id, event])
        const cacheTime = parseInt(DateTime.now().toFormat('yyyyMMdd', { timeZone: 'UTC' }))

        if (!this.eventDefinitionsCache.get(team.id)?.has(event)) {
            status.info('Inserting new event definition with last_seen_at')
            this.eventLastSeenCache.set(cacheKey, cacheTime)
            await this.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, last_seen_at, created_at)
VALUES ($1, $2, NULL, NULL, $3, $4, NOW()) ON CONFLICT
ON CONSTRAINT posthog_eventdefinition_team_id_name_80fa0b87_uniq DO UPDATE SET last_seen_at=$4`,
                [new UUIDT().toString(), event, team.id, DateTime.now()],
                'insertEventDefinition'
            )
            this.eventDefinitionsCache.get(team.id)?.add(event)
        } else {
            if ((this.eventLastSeenCache.get(cacheKey) ?? 0) < cacheTime) {
                this.eventLastSeenCache.set(cacheKey, cacheTime)
                await this.db.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `UPDATE posthog_eventdefinition SET last_seen_at=$1 WHERE team_id=$2 AND name=$3`,
                    [DateTime.now(), team.id, event],
                    'updateEventLastSeenAt'
                )
            }
        }
    }

    private async syncEventProperties(team: Team, event: string, properties: Properties) {
        const key = JSON.stringify([team.id, event])
        let existingProperties = this.eventPropertiesCache.get(key)
        const toInsert: Array<[string, string, TeamId]> = []
        if (!existingProperties) {
            existingProperties = new Set()
            this.eventPropertiesCache.set(key, existingProperties)
        }

        for (const property of this.getPropertyKeys(properties)) {
            if (!existingProperties.has(property)) {
                existingProperties.add(property)
                toInsert.push([event, property, team.id])
            }
        }

        await this.db.postgres.bulkInsert(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_eventproperty (event, property, team_id) VALUES {VALUES} ON CONFLICT DO NOTHING`,
            toInsert,
            'insertEventProperty'
        )
    }

    private async syncPropertyDefinitions(team: Team, event: string, properties: Properties) {
        const toInsert: Array<
            [string, string, number, number | null, boolean, null, null, TeamId, PropertyType | null]
        > = []
        for await (const { key, value, type, groupTypeIndex } of this.getPropertyDefinitions(
            team.id,
            event,
            properties
        )) {
            if (this.propertyDefinitionsCache.shouldUpdate(team.id, key, type, groupTypeIndex)) {
                const propertyType = detectPropertyDefinitionTypes(value, key)
                const isNumerical = propertyType == PropertyType.Numeric
                this.propertyDefinitionsCache.set(team.id, key, type, groupTypeIndex, propertyType)

                toInsert.push([
                    new UUIDT().toString(),
                    key,
                    type,
                    groupTypeIndex,
                    isNumerical,
                    null,
                    null,
                    team.id,
                    propertyType,
                ])
            }
        }

        await this.db.postgres.bulkInsert(
            PostgresUse.COMMON_WRITE,
            `
            INSERT INTO posthog_propertydefinition (id, name, type, group_type_index, is_numerical, volume_30_day, query_usage_30_day, team_id, property_type)
            VALUES {VALUES}
            ON CONFLICT (team_id, name, type, coalesce(group_type_index, -1))
            DO UPDATE SET property_type=EXCLUDED.property_type WHERE posthog_propertydefinition.property_type IS NULL
            `,
            toInsert,
            'insertPropertyDefinition'
        )
    }

    public async cacheEventNamesAndProperties(teamId: number, event: string): Promise<void> {
        let eventDefinitionsCache = this.eventDefinitionsCache.get(teamId)
        if (!eventDefinitionsCache) {
            const eventNames = await this.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                'SELECT name FROM posthog_eventdefinition WHERE team_id = $1',
                [teamId],
                'fetchEventDefinitions'
            )
            eventDefinitionsCache = new Set(eventNames.rows.map((r) => r.name))
            this.eventDefinitionsCache.set(teamId, eventDefinitionsCache)
        }

        if (!this.propertyDefinitionsCache.has(teamId)) {
            await this.propertyDefinitionsCache.initialize(teamId, this.db)
        }

        const cacheKey = JSON.stringify([teamId, event])
        let properties = this.eventPropertiesCache.get(cacheKey)
        if (!properties) {
            properties = new Set()
            this.eventPropertiesCache.set(cacheKey, properties)

            // The code above and below introduces a race condition. At this point we have an empty set in the cache,
            // and will be waiting for the query below to return. If at the same time, asynchronously, we start to
            // process another event with the same name for this team, `syncEventProperties` above will see the empty
            // cache and will start to insert (on conflict do nothing) all the properties for the event. This will
            // continue until either 1) the inserts will fill up the cache, or 2) the query below returns.
            // All-in-all, not the end of the world, but a slight nuisance.

            const eventProperties = await this.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                'SELECT property FROM posthog_eventproperty WHERE team_id = $1 AND event = $2',
                [teamId, event],
                'fetchEventProperties'
            )
            for (const { property } of eventProperties.rows) {
                properties.add(property)
            }
        }
    }

    private getPropertyKeys(properties: Properties): Array<string> {
        return Object.keys(properties).filter((key) => !NOT_SYNCED_PROPERTIES.has(key))
    }

    private async *getPropertyDefinitions(
        teamId: number,
        event: string,
        properties: Properties
    ): AsyncGenerator<PartialPropertyDefinition> {
        if (event === '$groupidentify') {
            const { $group_type: groupType, $group_set: groupPropertiesToSet } = properties
            if (groupType != null && groupPropertiesToSet != null) {
                const groupTypeIndex = await this.groupTypeManager.fetchGroupTypeIndex(teamId, groupType)
                // TODO: add further validation that group properties are of the
                // expected type
                yield* this.extract(groupPropertiesToSet, PropertyDefinitionTypeEnum.Group, groupTypeIndex)
            }
        } else {
            yield* this.extract(properties, PropertyDefinitionTypeEnum.Event)

            if (properties.$set) {
                yield* this.extract(properties.$set, PropertyDefinitionTypeEnum.Person)
            }
            if (properties.$set_once) {
                yield* this.extract(properties.$set_once, PropertyDefinitionTypeEnum.Person)
            }
        }
    }

    private *extract(
        properties: Properties,
        type: PropertyDefinitionTypeEnum,
        groupTypeIndex: GroupTypeIndex | null = null
    ): Generator<PartialPropertyDefinition> {
        for (const [key, value] of Object.entries(properties)) {
            if (type === PropertyDefinitionTypeEnum.Event && NOT_SYNCED_PROPERTIES.has(key)) {
                continue
            }
            yield {
                key,
                type,
                value,
                groupTypeIndex,
            }
        }
    }
}
