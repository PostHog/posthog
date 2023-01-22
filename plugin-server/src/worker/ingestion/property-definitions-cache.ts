import { StatsD } from 'hot-shots'
import LRU from 'lru-cache'
import LRUCache from 'lru-cache'

import { ONE_HOUR } from '../../config/constants'
import { GroupTypeIndex, PluginsServerConfig, PropertyDefinitionTypeEnum, PropertyType, TeamId } from '../../types'

export const NULL_IN_DATABASE = Symbol('NULL_IN_DATABASE')
export const NULL_AFTER_PROPERTY_TYPE_DETECTION = Symbol('NULL_AFTER_PROPERTY_TYPE_DETECTION')

type PropertyDefinitionsCacheValue = PropertyType | typeof NULL_IN_DATABASE | typeof NULL_AFTER_PROPERTY_TYPE_DETECTION

/**
 * During event ingestion the property definitions manager attempts to auto-detect the property type and format for properties
 *
 * The PropertyDefinitionsCache is used to reduce the load on Postgres
 * when inserting property definitions during event ingestion
 *
 * A property definition can be in one of several states
 *
 * - never seen before -> it is not in the cache and should be inserted into the database
 * - in the cache and has a property type -> it never needs to be updated
 * - in the cache and has null as a property type -> it might need property types inserted in postgres ('NULL_IN_DATABASE')
 * - it is in the cache and has been confirmed as having no property type -> it never needs to be updated ('NULL_AFTER_PROPERTY_TYPE_DETECTION')
 */
export class PropertyDefinitionsCache {
    private readonly propertyDefinitionsCache: Map<TeamId, LRU<string, PropertyDefinitionsCacheValue>>
    private readonly statsd?: StatsD
    private readonly lruCacheSize: number

    constructor(serverConfig: PluginsServerConfig, statsd?: StatsD) {
        this.lruCacheSize = serverConfig.EVENT_PROPERTY_LRU_SIZE
        this.statsd = statsd
        this.propertyDefinitionsCache = new Map()
    }

    initialize(
        teamId: number,
        items: {
            name: string
            property_type: PropertyDefinitionsCacheValue
        }[]
    ): void {
        const teamPropertyDefinitionsCache = new LRU<string, PropertyDefinitionsCacheValue>({
            max: this.lruCacheSize, // keep in memory the last 10k property definitions we have seen
            maxAge: ONE_HOUR * 24, // cache up to 24h
            updateAgeOnGet: true,
        })

        for (const item of items) {
            teamPropertyDefinitionsCache.set(item.name, item.property_type ?? NULL_IN_DATABASE)
        }

        this.propertyDefinitionsCache.set(teamId, teamPropertyDefinitionsCache)

        this.statsd?.gauge('propertyDefinitionsCache.length', teamPropertyDefinitionsCache.length ?? 0, {
            team_id: teamId.toString(),
        })
    }

    has(teamId: number): boolean {
        return this.propertyDefinitionsCache.has(teamId)
    }

    shouldUpdate(
        teamId: number,
        property: string,
        type: PropertyDefinitionTypeEnum,
        groupTypeIndex: GroupTypeIndex | null
    ): boolean {
        const teamCache = this.propertyDefinitionsCache.get(teamId)
        const value = teamCache?.get(this.key(property, type, groupTypeIndex))
        return value === undefined || value === NULL_IN_DATABASE
    }

    set(
        teamId: number,
        property: string,
        type: PropertyDefinitionTypeEnum,
        groupTypeIndex: GroupTypeIndex | null,
        detectedPropertyType: PropertyType | null
    ): void {
        const teamCache = this.propertyDefinitionsCache.get(teamId)
        teamCache?.set(
            this.key(property, type, groupTypeIndex),
            detectedPropertyType ?? NULL_AFTER_PROPERTY_TYPE_DETECTION
        )

        this.statsd?.gauge('propertyDefinitionsCache.length', teamCache?.length ?? 0, {
            team_id: teamId.toString(),
        })
    }

    get(teamId: number): LRUCache<string, string | symbol> | undefined {
        return this.propertyDefinitionsCache.get(teamId)
    }

    private key(property: string, type: PropertyDefinitionTypeEnum, groupTypeIndex: GroupTypeIndex | null): string {
        return `${type}${groupTypeIndex ?? ''}${property}`
    }
}
