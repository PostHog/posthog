import { DateTime } from 'luxon'

import { EventDefinitionType, EventPropertyType, Hub, PropertyDefinitionType } from '~/src/types'
import { PostgresUse } from '~/src/utils/db/postgres'

export class PropertyDefsDB {
    constructor(private hub: Hub) {}

    async writeEventProperty(eventProperty: EventPropertyType) {
        await this.hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_eventproperty (event, property, team_id, project_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
            `,
            [eventProperty.team_id, eventProperty.event, eventProperty.property, eventProperty.project_id],
            'upsertEventProperty'
        )
    }

    async writePropertyDefinition(propertyDefinition: PropertyDefinitionType) {
        await this.hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_propertydefinition (id, name, type, group_type_index, is_numerical, volume_30_day, query_usage_30_day, team_id, project_id, property_type)
        VALUES ($1, $2, $3, $4, $5, NULL, NULL, $6, $7, $8)
        ON CONFLICT (coalesce(project_id, team_id::bigint), name, type, coalesce(group_type_index, -1))
        DO UPDATE SET property_type=EXCLUDED.property_type WHERE posthog_propertydefinition.property_type IS NULL`,
            [
                propertyDefinition.id,
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
    }

    async writeEventDefinition(eventDefinition: EventDefinitionType) {
        await this.hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, project_id, last_seen_at, created_at)
        VALUES ($1, $2, NULL, NULL, $3, $4, $5, NOW())
        `,
            [
                eventDefinition.id,
                eventDefinition.name,
                eventDefinition.team_id,
                eventDefinition.project_id,
                DateTime.now().toISO(), // TODO: Should this be the event timestamp?
                DateTime.now().toISO(),
            ],
            'upsertEventDefinition'
        )
    }
}
