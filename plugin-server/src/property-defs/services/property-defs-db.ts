import { DateTime } from 'luxon'

import { EventDefinitionType, EventPropertyType, Hub, PropertyDefinitionType } from '~/src/types'

import { PostgresUse } from '../../utils/db/postgres'
import { status } from '../../utils/status'
import { UUIDT } from '../../utils/utils'

export class PropertyDefsDB {
    constructor(private hub: Hub) {}

    async writeEventProperty(eventProperty: EventPropertyType) {
        await this.hub.postgres
            .query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_eventproperty (event, property, team_id, project_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            `,
                [eventProperty.event, eventProperty.property, eventProperty.team_id, eventProperty.project_id],
                'upsertEventProperty'
            )
            .catch((e) => {
                status.error('🔁', `Error writing event property`, { eventProperty, error: e.message })
                throw e
            })
    }

    async writePropertyDefinition(propertyDefinition: PropertyDefinitionType) {
        await this.hub.postgres
            .query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_propertydefinition (id, name, type, group_type_index, is_numerical, team_id, project_id, property_type, volume_30_day, query_usage_30_day)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NULL, NULL)
        ON CONFLICT (coalesce(project_id, team_id::bigint), name, type, coalesce(group_type_index, -1))
        DO UPDATE SET property_type=EXCLUDED.property_type WHERE posthog_propertydefinition.property_type IS NULL`,
                [
                    new UUIDT().toString(),
                    propertyDefinition.name,
                    propertyDefinition.type,
                    propertyDefinition.group_type_index,
                    propertyDefinition.is_numerical,
                    propertyDefinition.team_id,
                    propertyDefinition.project_id,
                    propertyDefinition.property_type,
                ],
                'upsertPropertyDefinition'
            )
            .catch((e) => {
                status.error('🔁', `Error writing property definition`, { propertyDefinition, error: e.message })
                throw e
            })
    }

    async writeEventDefinition(eventDefinition: EventDefinitionType) {
        await this.hub.postgres
            .query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_eventdefinition (id, name, team_id, project_id, last_seen_at, created_at, volume_30_day, query_usage_30_day)
        VALUES ($1, $2, $3, $4, $5, $6, NULL, NULL)
        `,
                [
                    new UUIDT().toString(),
                    eventDefinition.name,
                    eventDefinition.team_id,
                    eventDefinition.project_id,
                    DateTime.now().toISO(), // TODO: Should this be the event timestamp?
                    DateTime.now().toISO(),
                ],
                'upsertEventDefinition'
            )
            .catch((e) => {
                status.error('🔁', `Error writing event definition`, { eventDefinition, error: e.message })
                throw e
            })
    }

    async listPropertyDefinitions(teamId: number): Promise<PropertyDefinitionType[]> {
        const result = await this.hub.postgres.query<PropertyDefinitionType>(
            PostgresUse.COMMON_READ,
            `SELECT * FROM posthog_propertydefinition WHERE team_id = $1`,
            [teamId],
            'listPropertyDefinitions'
        )

        return result.rows
    }

    async listEventDefinitions(teamId: number): Promise<EventDefinitionType[]> {
        const result = await this.hub.postgres.query<EventDefinitionType>(
            PostgresUse.COMMON_READ,
            `SELECT * FROM posthog_eventdefinition WHERE team_id = $1`,
            [teamId],
            'listEventDefinitions'
        )

        return result.rows
    }

    async listEventProperties(teamId: number): Promise<EventPropertyType[]> {
        const result = await this.hub.postgres.query<EventPropertyType>(
            PostgresUse.COMMON_READ,
            `SELECT * FROM posthog_eventproperty WHERE team_id = $1`,
            [teamId],
            'listEventProperties'
        )

        return result.rows
    }
}
