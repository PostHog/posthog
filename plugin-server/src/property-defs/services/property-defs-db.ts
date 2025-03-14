import { DateTime } from 'luxon'

import { EventDefinitionType, EventPropertyType, Hub, PropertyDefinitionType } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { status } from '../../utils/status'

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

    async writeEventProperties(eventProperties: EventPropertyType[]) {
        await this.hub.postgres
            .query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_eventproperty (event, property, team_id, project_id)
                    VALUES (UNNEST($1::text[]), UNNEST($2::text[]), UNNEST($3::int[]), UNNEST($4::int[]))
                    ON CONFLICT DO NOTHING
                `,
                [
                    eventProperties.map((ep) => ep.event),
                    eventProperties.map((ep) => ep.property),
                    eventProperties.map((ep) => ep.team_id),
                    eventProperties.map((ep) => ep.project_id),
                ],
                'upsertEventPropertiesBatch'
            )
            .catch((e) => {
                status.error('🔁', `Error writing event properties batch`, { eventProperties, error: e.message })
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
                    DO UPDATE SET property_type=EXCLUDED.property_type
                    WHERE posthog_propertydefinition.property_type IS NULL`,
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
            .catch((e) => {
                status.error('🔁', `Error writing property definitions batch`, {
                    propertyDefinition,
                    error: e.message,
                })
                throw e
            })
    }

    async writePropertyDefinitions(propertyDefinitions: PropertyDefinitionType[]) {
        await this.hub.postgres
            .query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_propertydefinition (id, name, type, group_type_index, is_numerical, team_id, project_id, property_type, volume_30_day, query_usage_30_day)
                    VALUES (UNNEST($1::uuid[]), UNNEST($2::text[]), UNNEST($3::smallint[]), UNNEST($4::int[]), UNNEST($5::boolean[]), UNNEST($6::int[]), UNNEST($7::int[]), UNNEST($8::text[]), NULL, NULL)
                    ON CONFLICT (coalesce(project_id, team_id::bigint), name, type, coalesce(group_type_index, -1))
                    DO UPDATE SET property_type=EXCLUDED.property_type
                    WHERE posthog_propertydefinition.property_type IS NULL
                `,
                [
                    propertyDefinitions.map((pd) => pd.id),
                    propertyDefinitions.map((pd) => pd.name),
                    propertyDefinitions.map((pd) => pd.type),
                    propertyDefinitions.map((pd) => pd.group_type_index),
                    propertyDefinitions.map((pd) => pd.is_numerical),
                    propertyDefinitions.map((pd) => pd.team_id),
                    propertyDefinitions.map((pd) => pd.project_id),
                    propertyDefinitions.map((pd) => pd.property_type),
                ],
                'upsertPropertyDefinitionsBatch'
            )
            .catch((e) => {
                status.error('🔁', `Error writing property definitions batch`, {
                    propertyDefinitions,
                    error: e.message,
                })
                throw e
            })
    }

    async writeEventDefinition(eventDefinition: EventDefinitionType) {
        await this.hub.postgres
            .query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_eventdefinition (id, name, team_id, project_id, last_seen_at, created_at, volume_30_day, query_usage_30_day)
                    VALUES ($1, $2, $3, $4, $5, $6, NULL, NULL)
                    ON CONFLICT (coalesce(project_id, team_id::bigint), name)
                    DO UPDATE SET last_seen_at=EXCLUDED.last_seen_at WHERE posthog_eventdefinition.last_seen_at < EXCLUDED.last_seen_at
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
            .catch((e) => {
                status.error('🔁', `Error writing event definition`, { eventDefinition, error: e.message })
                throw e
            })
    }

    async writeEventDefinitions(eventDefinitions: EventDefinitionType[]) {
        const now = DateTime.now().toISO()
        await this.hub.postgres
            .query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_eventdefinition (id, name, team_id, project_id, last_seen_at, created_at, volume_30_day, query_usage_30_day)
                    VALUES (UNNEST($1::uuid[]), UNNEST($2::text[]), UNNEST($3::int[]), UNNEST($4::int[]), UNNEST($5::timestamp[]), UNNEST($6::timestamp[]), NULL, NULL)
                    ON CONFLICT (coalesce(project_id, team_id::bigint), name)
                    DO UPDATE SET last_seen_at=EXCLUDED.last_seen_at WHERE posthog_eventdefinition.last_seen_at < EXCLUDED.last_seen_at
                `,
                [
                    eventDefinitions.map((ed) => ed.id),
                    eventDefinitions.map((ed) => ed.name),
                    eventDefinitions.map((ed) => ed.team_id),
                    eventDefinitions.map((ed) => ed.project_id),
                    eventDefinitions.map(() => now),
                    eventDefinitions.map(() => now),
                ],
                'upsertEventDefinitionsBatch'
            )
            .catch((e) => {
                status.error('🔁', `Error writing event definitions batch`, { eventDefinitions, error: e.message })
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
