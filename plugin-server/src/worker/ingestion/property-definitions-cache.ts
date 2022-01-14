import { StatsD } from 'hot-shots'
import LRU from 'lru-cache'
import LRUCache from 'lru-cache'

import { ONE_HOUR } from '../../config/constants'
import { PluginsServerConfig, PropertyType, TeamId } from '../../types'

export const NULL_IN_DATABASE = Symbol('NULL_IN_DATABASE')
export const NULL_AFTER_PROPERTY_TYPE_DETECTION = Symbol('NULL_AFTER_PROPERTY_TYPE_DETECTION')

/**
 * The PropertyDefinitionsCache is used to reduce the load on Postgres when inserting property definitions during event ingestion
 *
 * A property definition can be in one of several states
 *
 * - never seen before -> it is not in the cache and should be inserted into the database
 * - in the cache and has a property type -> it never needs to be updated
 * - in the cache and has null as a property type -> it might need property types inserted in postgres ('NULL_IN_DATABASE')
 * - it is in the cache and has been confirmed as having no property type -> it never needs to be updated ('NULL_AFTER_PROPERTY_TYPE_DETECTION')
 */
export class PropertyDefinitionsCache {
    private readonly propertyDefinitionsCache: Map<TeamId, LRU<string, string | symbol>>
    private readonly statsd?: StatsD
    private readonly lruCacheSize: number

    constructor(serverConfig: PluginsServerConfig, statsd?: StatsD) {
        this.lruCacheSize = serverConfig.EVENT_PROPERTY_LRU_SIZE
        this.statsd = statsd
        this.propertyDefinitionsCache = new Map()
    }

    initialize(teamId: number, items: any[]): void {
        const teamPropertyDefinitionsCache = new LRU<string, string | symbol>({
            max: this.lruCacheSize, // keep in memory the last 10k property definitions we have seen
            maxAge: ONE_HOUR * 24, // cache up to 24h
            updateAgeOnGet: true,
        })

        for (const row of items) {
            teamPropertyDefinitionsCache.set(row.name, row.property_type ?? NULL_IN_DATABASE)
        }

        this.propertyDefinitionsCache.set(teamId, teamPropertyDefinitionsCache)

        this.statsd?.gauge('propertyDefinitionsCache.length', teamPropertyDefinitionsCache.length ?? 0, {
            team_id: teamId.toString(),
        })
    }

    has(teamId: number): boolean {
        return this.propertyDefinitionsCache.has(teamId)
    }

    shouldUpdate(teamId: number, key: string): boolean {
        return (
            !this.propertyDefinitionsCache.get(teamId)?.has(key) ||
            this.propertyDefinitionsCache.get(teamId)?.get(key) === NULL_IN_DATABASE
        )
    }

    set(teamId: number, key: string, propertyType: null | PropertyType.Numeric | PropertyType.String): void {
        const teamCache = this.propertyDefinitionsCache.get(teamId)
        teamCache?.set(key, propertyType || NULL_AFTER_PROPERTY_TYPE_DETECTION)

        this.statsd?.gauge('propertyDefinitionsCache.length', teamCache?.length ?? 0, {
            team_id: teamId.toString(),
        })
    }

    get(teamId: number): LRUCache<string, string | symbol> | undefined {
        return this.propertyDefinitionsCache.get(teamId)
    }
}
