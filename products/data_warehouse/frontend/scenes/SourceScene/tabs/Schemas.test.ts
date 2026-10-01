import { ExternalDataSchemaStatus, type ExternalDataSourceSchema } from '~/types'

import { schemaHasNoTableYet } from 'products/data_warehouse/frontend/utils'

import { groupDirectQuerySourceSchemasBySchema, splitDirectQuerySchemaName } from './DirectQuerySchemasTab'

const makeSchema = (name: string): ExternalDataSourceSchema => ({
    id: name,
    name,
    label: null,
    should_sync: true,
    incremental: false,
    sync_type: null,
    sync_time_of_day: null,
    latest_error: null,
    incremental_field: null,
    incremental_field_type: null,
    sync_frequency: '6hour',
    primary_key_columns: null,
})

describe('Schemas', () => {
    it('splits a qualified direct query table name into schema and table names', () => {
        expect(splitDirectQuerySchemaName('public.events')).toEqual({
            schemaName: 'public',
            tableName: 'events',
        })
    })

    it('uses the selected source schema for unqualified direct query table names', () => {
        expect(splitDirectQuerySchemaName('events', 'posthog')).toEqual({
            schemaName: 'posthog',
            tableName: 'events',
        })
    })

    it('groups direct query source schemas by schema name', () => {
        expect(
            groupDirectQuerySourceSchemasBySchema([
                makeSchema('analytics.pageviews'),
                makeSchema('public.events'),
                makeSchema('analytics.sessions'),
            ])
        ).toEqual([
            {
                schemaName: 'analytics',
                schemas: [makeSchema('analytics.pageviews'), makeSchema('analytics.sessions')],
            },
            {
                schemaName: 'public',
                schemas: [makeSchema('public.events')],
            },
        ])
    })

    it('groups unqualified direct query source schemas under the configured source schema', () => {
        expect(groupDirectQuerySourceSchemasBySchema([makeSchema('events')], 'posthog')).toEqual([
            {
                schemaName: 'posthog',
                schemas: [makeSchema('events')],
            },
        ])
    })

    it.each([
        ['a completed sync that registered no table', ExternalDataSchemaStatus.Completed, false, true, true],
        ['a completed sync with a table', ExternalDataSchemaStatus.Completed, true, true, false],
        ['a sync still running', ExternalDataSchemaStatus.Running, false, true, false],
        ['a failed sync', ExternalDataSchemaStatus.Failed, false, true, false],
        ['a schema discovery turned off', ExternalDataSchemaStatus.Completed, false, false, false],
    ])('detects no table yet for %s', (_label, status, hasTable, shouldSync, expected) => {
        const schema = {
            ...makeSchema('events'),
            status,
            should_sync: shouldSync,
            table: hasTable ? ({ id: 'table-1' } as ExternalDataSourceSchema['table']) : undefined,
        }
        expect(schemaHasNoTableYet(schema)).toBe(expected)
    })
})
