import { EventSchemaEnforcement, EventSchemaProperty } from '../types'
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
    is_required: boolean
}

/**
 * Manages event schema enforcement configuration for teams.
 *
 * Fetches schemas for events that have enforcement_mode='reject' on their EventSchema,
 * which are validated at ingestion time.
 */
export class EventSchemaEnforcementManager {
    private lazyLoader: LazyLoader<EventSchemaEnforcement[]>

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
     * Get enforced event schemas for a team.
     * Returns an empty array if no schemas are configured for enforcement.
     */
    public async getSchemas(teamId: number): Promise<EventSchemaEnforcement[]> {
        return (await this.lazyLoader.get(String(teamId))) ?? []
    }

    /**
     * Get enforced event schemas for multiple teams.
     */
    public async getSchemasForTeams(teamIds: number[]): Promise<Record<string, EventSchemaEnforcement[]>> {
        const results = await this.lazyLoader.getMany(teamIds.map(String))
        const converted: Record<string, EventSchemaEnforcement[]> = {}
        for (const [key, value] of Object.entries(results)) {
            converted[key] = value ?? []
        }
        return converted
    }

    private async fetchSchemas(teamIds: string[]): Promise<Record<string, EventSchemaEnforcement[] | null>> {
        const numericTeamIds = teamIds.map(Number).filter((id) => !isNaN(id) && id > 0)

        if (numericTeamIds.length === 0) {
            const result: Record<string, EventSchemaEnforcement[] | null> = {}
            for (const id of teamIds) {
                result[id] = null
            }
            return result
        }

        // Simple flat query - aggregation happens in JS
        const queryResult = await this.postgres.query<RawSchemaPropertyRow>(
            PostgresUse.COMMON_READ,
            `SELECT
                ed.team_id,
                ed.name as event_name,
                p.name as property_name,
                p.property_type,
                p.is_required
            FROM posthog_eventdefinition ed
            JOIN posthog_eventschema es ON es.event_definition_id = ed.id
            JOIN posthog_schemapropertygroup pg ON pg.id = es.property_group_id
            JOIN posthog_schemapropertygroupproperty p ON p.property_group_id = pg.id
            WHERE ed.team_id = ANY($1)
              AND es.enforcement_mode = 'reject'
              AND p.is_required = true
            ORDER BY ed.team_id, ed.name, p.name`,
            [numericTeamIds],
            'fetch-enforced-event-schemas'
        )

        // Aggregate rows into EventSchemaEnforcement structures
        const schemasByTeam = this.aggregateRows(queryResult.rows)

        // Build result with nulls for teams that weren't found
        const result: Record<string, EventSchemaEnforcement[] | null> = {}
        for (const id of teamIds) {
            result[id] = schemasByTeam[id] ?? null
        }

        return result
    }

    /**
     * Aggregates flat rows into nested EventSchemaEnforcement structures.
     *
     * Input: One row per (team, event, property, property_type)
     * Output: Grouped by team -> event -> property (with merged property_types)
     */
    private aggregateRows(rows: RawSchemaPropertyRow[]): Record<string, EventSchemaEnforcement[]> {
        // team_id -> event_name -> property_name -> property_types[]
        const teamEventProps: Record<string, Record<string, Record<string, Set<string>>>> = {}

        for (const row of rows) {
            const teamId = String(row.team_id)
            if (!teamEventProps[teamId]) {
                teamEventProps[teamId] = {}
            }
            if (!teamEventProps[teamId][row.event_name]) {
                teamEventProps[teamId][row.event_name] = {}
            }
            if (!teamEventProps[teamId][row.event_name][row.property_name]) {
                teamEventProps[teamId][row.event_name][row.property_name] = new Set()
            }
            teamEventProps[teamId][row.event_name][row.property_name].add(row.property_type)
        }

        // Convert to final structure
        const result: Record<string, EventSchemaEnforcement[]> = {}
        for (const [teamId, events] of Object.entries(teamEventProps)) {
            result[teamId] = []
            for (const [eventName, properties] of Object.entries(events)) {
                const requiredProperties: EventSchemaProperty[] = []
                for (const [propName, propTypes] of Object.entries(properties)) {
                    requiredProperties.push({
                        name: propName,
                        property_types: Array.from(propTypes),
                        is_required: true,
                    })
                }
                result[teamId].push({
                    event_name: eventName,
                    required_properties: requiredProperties,
                })
            }
        }

        return result
    }
}
