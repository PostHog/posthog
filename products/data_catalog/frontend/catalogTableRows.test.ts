import type {
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaTable,
    DatabaseSchemaViewTable,
} from '~/queries/schema/schema-general'

import type { DataQualityOverviewCheckApi } from 'products/data_quality/frontend/generated/api.schemas'
import { groupChecksBySubject } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { CatalogTableRow, TablesFilter, buildCatalogTableRows, rowMatchesFilter } from './catalogTableRows'
import type { DataCatalogCertificationApi } from './generated/api.schemas'

function check(
    subjectType: string,
    subjectUuid: string,
    subjectName: string,
    lastStatus: string
): DataQualityOverviewCheckApi {
    return {
        id: `${subjectName}-${lastStatus}`,
        subject_type: subjectType,
        subject_uuid: subjectUuid,
        subject_name: subjectName,
        last_status: lastStatus,
    } as unknown as DataQualityOverviewCheckApi
}

const events = { type: 'posthog', id: 'events', name: 'events', fields: {} } as DatabaseSchemaTable
const sessions = { type: 'posthog', id: 'sessions', name: 'sessions', fields: {} } as DatabaseSchemaTable
const charges = {
    type: 'data_warehouse',
    id: 'table-charges',
    name: 'stripe.charges',
    fields: {},
    source: { id: 'source-1', source_type: 'Stripe', status: 'Completed', prefix: '', last_synced_at: 'source-sync' },
    schema: { id: 'schema-1', name: 'charges', should_sync: true, incremental: false, last_synced_at: 'schema-sync' },
} as unknown as DatabaseSchemaDataWarehouseTable
const ordersDaily = { type: 'view', id: 'query-orders', name: 'orders_daily', fields: {} } as DatabaseSchemaViewTable

function buildRows(): CatalogTableRow[] {
    const checks = [
        check('posthog_table', 'events-uuid', 'events', 'failed'),
        check('table', 'table-charges', 'stripe.charges', 'passed'),
        check('view', 'query-gone', 'deleted_view', 'passed'),
        check('metric', 'metric-1', 'mrr', 'failed'),
    ]
    return buildCatalogTableRows({
        posthogTables: [events, sessions],
        dataWarehouseTables: [charges],
        views: [ordersDaily],
        checkGroups: groupChecksBySubject(checks, {}),
        certifications: [
            { id: 'cert-orders', saved_query: 'query-orders', table: null, status: 'proposed' },
            { id: 'cert-charges', saved_query: null, table: 'table-charges', status: 'certified' },
        ] as DataCatalogCertificationApi[],
        nodes: [],
        posthogTableSubjectIds: { events: 'events-uuid' },
    })
}

describe('catalogTableRows', () => {
    it('joins checks, certifications and freshness onto each table, failing tables first', () => {
        const rows = buildRows()

        expect(
            rows.map((row) => ({
                name: row.name,
                origin: row.origin,
                checks: row.checkGroup?.checks.length ?? 0,
                failing: row.failingCheckCount,
                trust: row.certification?.id ?? null,
                refreshedAt: row.refreshedAt,
            }))
        ).toEqual([
            { name: 'events', origin: 'PostHog', checks: 1, failing: 1, trust: null, refreshedAt: null },
            { name: 'deleted_view', origin: 'Your view', checks: 1, failing: 0, trust: null, refreshedAt: null },
            {
                name: 'orders_daily',
                origin: 'Your view',
                checks: 0,
                failing: 0,
                trust: 'cert-orders',
                refreshedAt: null,
            },
            { name: 'sessions', origin: 'PostHog', checks: 0, failing: 0, trust: null, refreshedAt: null },
            {
                name: 'stripe.charges',
                origin: 'Stripe',
                checks: 1,
                failing: 0,
                trust: 'cert-charges',
                refreshedAt: 'schema-sync',
            },
        ])
    })

    it.each<[TablesFilter, string[]]>([
        ['failing', ['events']],
        ['no_checks', ['orders_daily', 'sessions']],
        ['proposed', ['orders_daily']],
        ['certified', ['stripe.charges']],
        ['deprecated', []],
        ['all', ['events', 'deleted_view', 'orders_daily', 'sessions', 'stripe.charges']],
    ])('the %s filter keeps %j', (filter, expectedNames) => {
        expect(
            buildRows()
                .filter((row) => rowMatchesFilter(row, filter))
                .map((row) => row.name)
        ).toEqual(expectedNames)
    })
})
