import type { ExternalDataSourceSyncSchema } from '~/types'

import { getDirectQuerySelectionDescription } from './SchemaForm'
import { getDefaultExpandedSchemaKeys, groupTablesBySchema, splitQualifiedTableName } from './schemaGroupingUtils'

const makeSchema = (table: string): ExternalDataSourceSyncSchema => ({
    table,
    should_sync: true,
    sync_time_of_day: null,
    incremental_field: null,
    incremental_field_type: null,
    sync_type: null,
    incremental_fields: [],
    incremental_available: false,
    append_available: false,
    supports_webhooks: false,
    should_sync_default: true,
    primary_key_columns: null,
    available_columns: [],
    detected_primary_keys: null,
})

describe('SchemaForm', () => {
    it('describes browsing across all schemas when the schema is blank', () => {
        expect(getDirectQuerySelectionDescription('')).toEqual(
            "Query selected Postgres tables from within PostHog. Tables stay in the source database and are not synced into the data warehouse. You can't join data from these tables with other data in the PostHog warehouse. Enable each schema to choose which tables should be queryable."
        )
    })

    it('describes the selected schema when one is set', () => {
        expect(getDirectQuerySelectionDescription(' public ')).toEqual(
            `Query selected Postgres tables from within PostHog. Tables stay in the source database and are not synced into the data warehouse. You can't join data from these tables with other data in the PostHog warehouse. Choose which tables from the "public" schema should be queryable.`
        )
    })

    it('splits fully qualified table names into schema and table labels', () => {
        expect(splitQualifiedTableName('public.events')).toEqual({
            schemaName: 'public',
            tableName: 'events',
        })
    })

    it('uses the selected schema as a fallback for unqualified table names', () => {
        expect(splitQualifiedTableName('events', 'public')).toEqual({
            schemaName: 'public',
            tableName: 'events',
        })
    })

    it('groups tables by schema', () => {
        expect(
            groupTablesBySchema(
                [makeSchema('analytics.pageviews'), makeSchema('public.events'), makeSchema('analytics.sessions')],
                (schema) => schema.table
            )
        ).toEqual([
            {
                schemaName: 'analytics',
                tables: [makeSchema('analytics.pageviews'), makeSchema('analytics.sessions')],
            },
            {
                schemaName: 'public',
                tables: [makeSchema('public.events')],
            },
        ])
    })

    it('expands all schema groups by default', () => {
        expect(
            getDefaultExpandedSchemaKeys(
                groupTablesBySchema(
                    [makeSchema('analytics.pageviews'), makeSchema('public.events'), makeSchema('analytics.sessions')],
                    (schema) => schema.table
                )
            )
        ).toEqual(['analytics', 'public'])
    })
})
