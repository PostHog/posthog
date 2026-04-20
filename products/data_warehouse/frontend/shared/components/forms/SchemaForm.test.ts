import type { ExternalDataSourceSyncSchema } from '~/types'

import {
    getDefaultExpandedDirectQuerySchemaKeys,
    groupDirectQueryTablesBySchema,
    splitDirectQueryTableName,
} from './directQuerySchemaUtils'
import { getDirectQuerySelectionDescription } from './SchemaForm'

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
        expect(splitDirectQueryTableName('public.events')).toEqual({
            schemaName: 'public',
            tableName: 'events',
        })
    })

    it('uses the selected schema as a fallback for unqualified table names', () => {
        expect(splitDirectQueryTableName('events', 'public')).toEqual({
            schemaName: 'public',
            tableName: 'events',
        })
    })

    it('groups direct query tables by schema', () => {
        expect(
            groupDirectQueryTablesBySchema([
                makeSchema('analytics.pageviews'),
                makeSchema('public.events'),
                makeSchema('analytics.sessions'),
            ])
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

    it('expands all direct query schema groups by default', () => {
        expect(
            getDefaultExpandedDirectQuerySchemaKeys(
                groupDirectQueryTablesBySchema([
                    makeSchema('analytics.pageviews'),
                    makeSchema('public.events'),
                    makeSchema('analytics.sessions'),
                ])
            )
        ).toEqual(['analytics', 'public'])
    })
})
