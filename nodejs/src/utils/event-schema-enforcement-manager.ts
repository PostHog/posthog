import { EventSchemaEnforcement } from '../types'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'

/**
 * Raw row from the database query - one row per property per event.
 * We aggregate these in JS to build the EventSchemaEnforcement structure.
 */
interface RawSchemaPropertyRow {
    team_id: number
    event_name: string
    property_name: string
    property_type: string
}

/**
 * Manages event schema enforcement configuration for teams.
 *
 * Fetches schemas for events that have enforcement_mode='reject' on their EventDefinition,
 * which are validated at ingestion time.
 */
/** Map from event_name to schema for O(1) lookups */
export type EventSchemaMap = Map<string, EventSchemaEnforcement>

export class EventSchemaEnforcementManager {
    private lazyLoader: LazyLoader<EventSchemaMap>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'EventSchemaEnforcementManager',
            refreshAgeMs: 2 * 60 * 1000, // 2 minutes
            refreshJitterMs: 30 * 1000, // 30 seconds
            loader: async (teamIds: string[]) => {
                return await this.fetchSchemas(teamIds)
            },
        })
    }

    /**
     * Get enforced event schemas for a team as a Map keyed by event_name for O(1) lookups.
     * Returns an empty Map if no schemas are configured for enforcement.
     */
    public async getSchemas(teamId: number): Promise<EventSchemaMap> {
        return (await this.lazyLoader.get(String(teamId))) ?? new Map()
    }

    /**
     * Get enforced event schemas for multiple teams.
     */
    public async getSchemasForTeams(teamIds: number[]): Promise<Record<string, EventSchemaMap>> {
        const results = await this.lazyLoader.getMany(teamIds.map(String))
        const converted: Record<string, EventSchemaMap> = {}
        for (const [key, value] of Object.entries(results)) {
            converted[key] = value ?? new Map()
        }
        return converted
    }

    private async fetchSchemas(teamIds: string[]): Promise<Record<string, EventSchemaMap | null>> {
        const numericTeamIds = teamIds.map(Number).filter((id) => !isNaN(id) && id > 0)

        if (numericTeamIds.length === 0) {
            const result: Record<string, EventSchemaMap | null> = {}
            for (const id of teamIds) {
                result[id] = null
            }
            return result
        }

        // Properties that have conflicting types across property groups are excluded
        // from validation (HAVING COUNT(DISTINCT ...) = 1) since misconfigured
        // properties should not block ingestion.
        const queryResult = await this.postgres.query<RawSchemaPropertyRow>(
            PostgresUse.COMMON_READ,
            `SELECT
                ed.team_id,
                ed.name as event_name,
                p.name as property_name,
                MIN(p.property_type) as property_type
            FROM posthog_eventdefinition ed
            JOIN posthog_eventschema es ON es.event_definition_id = ed.id
            JOIN posthog_schemapropertygroupproperty p ON p.property_group_id = es.property_group_id
            WHERE ed.team_id = ANY($1)
              AND ed.enforcement_mode = 'reject'
              AND p.is_required = true
            GROUP BY ed.team_id, ed.name, p.name
            HAVING COUNT(DISTINCT p.property_type) = 1
            ORDER BY ed.team_id, ed.name, p.name`,
            [numericTeamIds],
            'fetch-enforced-event-schemas'
        )

        // Aggregate rows into EventSchemaMap structures (Map keyed by event_name)
        const schemasByTeam = this.aggregateRows(queryResult.rows)

        // Build result with nulls for teams that weren't found
        const result: Record<string, EventSchemaMap | null> = {}
        for (const id of teamIds) {
            result[id] = schemasByTeam[id] ?? null
        }

        return result
    }

    private aggregateRows(rows: RawSchemaPropertyRow[]): Record<string, EventSchemaMap> {
        const result: Record<string, EventSchemaMap> = {}

        for (const row of rows) {
            const teamId = String(row.team_id)
            if (!result[teamId]) {
                result[teamId] = new Map()
            }

            let schema = result[teamId].get(row.event_name)
            if (!schema) {
                schema = { event_name: row.event_name, required_properties: new Map() }
                result[teamId].set(row.event_name, schema)
            }

            schema.required_properties.set(row.property_name, row.property_type)
        }

        return result
    }
}
