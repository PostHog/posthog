import type { DataWarehouseSavedQuerySummary } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import {
    type DatabaseSchemaDataWarehouseTable,
    type DatabaseSchemaManagedViewTable,
    type DatabaseSchemaTable,
    type DatabaseSchemaViewTable,
    DataWarehouseSavedQueryOrigin,
} from '~/queries/schema/schema-general'
import type { DataModelingNode } from '~/types'

import type { MaterializationProblem } from 'products/data_modeling/frontend/modelsOverviewLogic'
import type { AttentionModel } from 'products/data_modeling/frontend/modelsSceneLogic'
import type { DataQualityOverviewCheckApi } from 'products/data_quality/frontend/generated/api.schemas'
import { groupChecksBySubject } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import {
    CatalogTableRow,
    CatalogTableSources,
    DEFAULT_TABLES_FILTERS,
    TablesFilters,
    TablesSort,
    buildCatalogTableRows,
    rowMatchesFilters,
    sortCatalogTableRows,
} from './catalogTableRows'
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

function savedQuery(
    id: string,
    name: string,
    overrides: Partial<DataWarehouseSavedQuerySummary> = {}
): DataWarehouseSavedQuerySummary {
    return {
        id,
        name,
        is_materialized: false,
        origin: 'data_warehouse',
        managed_viewset_kind: null,
        ...overrides,
    } as DataWarehouseSavedQuerySummary
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
const ordersExport = {
    type: 'data_warehouse',
    id: 'table-orders-export',
    name: 'orders_export',
    fields: {},
} as unknown as DatabaseSchemaDataWarehouseTable
const view = (id: string, name: string): DatabaseSchemaViewTable =>
    ({ type: 'view', id, name, fields: {} }) as unknown as DatabaseSchemaViewTable

const revenueNode = {
    id: 'node-revenue',
    name: 'revenue',
    saved_query_id: 'query-revenue',
    downstream_count: 3,
    last_run_at: 'revenue-run',
} as DataModelingNode
const revenueSuspended: MaterializationProblem = {
    kind: 'suspended',
    attention: { node: revenueNode, problem: 'Suspended' } as AttentionModel,
}

function buildRows(overrides: Partial<CatalogTableSources> = {}): CatalogTableRow[] {
    const checks = [
        check('posthog_table', 'events-uuid', 'events', 'failed'),
        check('table', 'table-charges', 'stripe.charges', 'passed'),
        check('view', 'query-gone', 'deleted_view', 'passed'),
        check('view', 'query-api', 'api_v1', 'passed'),
        check('metric', 'metric-1', 'mrr', 'failed'),
    ]
    return buildCatalogTableRows({
        posthogTables: [events, sessions],
        dataWarehouseTables: [charges, ordersExport],
        views: [view('query-orders', 'orders_daily'), view('query-revenue', 'revenue'), view('query-api', 'api_v1')],
        savedQueries: [
            savedQuery('query-orders', 'orders_daily'),
            savedQuery('query-revenue', 'revenue', { is_materialized: true }),
            savedQuery('query-api', 'api_v1', { origin: DataWarehouseSavedQueryOrigin.ENDPOINT }),
        ],
        checkGroups: groupChecksBySubject(checks, {}),
        certifications: [
            { id: 'cert-orders', saved_query: 'query-orders', table: null, status: 'proposed' },
            { id: 'cert-charges', saved_query: null, table: 'table-charges', status: 'certified' },
        ] as DataCatalogCertificationApi[],
        nodes: [revenueNode],
        materializationProblems: [revenueSuspended],
        posthogTableSubjectIds: { events: 'events-uuid' },
        managedViews: [],
        healthBySubjectKey: {},
        ...overrides,
    })
}

describe('catalogTableRows', () => {
    it('joins refresh problems, checks and certifications onto every queryable table, problems first', () => {
        expect(
            buildRows().map((row) => ({
                name: row.name,
                subtitle: row.subtitle,
                problems: row.problems,
                checks: row.checkGroup?.checks.length ?? 0,
                trust: row.certification?.id ?? null,
                refreshedAt: row.refreshedAt,
            }))
        ).toEqual([
            {
                name: 'revenue',
                subtitle: 'Materialized view · feeds 3\u00a0models',
                problems: ['suspended'],
                checks: 0,
                trust: null,
                refreshedAt: 'revenue-run',
            },
            { name: 'events', subtitle: 'PostHog', problems: ['checks'], checks: 1, trust: null, refreshedAt: null },
            { name: 'deleted_view', subtitle: 'View', problems: [], checks: 1, trust: null, refreshedAt: null },
            {
                name: 'orders_daily',
                subtitle: 'View',
                problems: [],
                checks: 0,
                trust: 'cert-orders',
                refreshedAt: null,
            },
            {
                name: 'orders_export',
                subtitle: 'Self-managed',
                problems: [],
                checks: 0,
                trust: null,
                refreshedAt: null,
            },
            { name: 'sessions', subtitle: 'PostHog', problems: [], checks: 0, trust: null, refreshedAt: null },
            {
                name: 'stripe.charges',
                subtitle: 'Stripe',
                problems: [],
                checks: 1,
                trust: 'cert-charges',
                refreshedAt: 'schema-sync',
            },
        ])
    })

    it.each<[Partial<TablesFilters>, string[]]>([
        [{ kind: 'materialized_view' }, ['revenue']],
        [{ kind: 'posthog' }, ['events', 'sessions']],
        [{ problem: 'checks' }, ['events']],
        [{ trust: 'proposed' }, ['orders_daily']],
        [{ kind: 'self_managed' }, ['orders_export']],
        [{ trust: 'none' }, ['revenue', 'events', 'deleted_view', 'orders_export', 'sessions']],
        [{ checks: 'without' }, ['revenue', 'orders_daily', 'orders_export', 'sessions']],
        [{ kind: 'source', trust: 'certified', checks: 'with' }, ['stripe.charges']],
    ])('filters %j keep %j', (filters, expectedNames) => {
        expect(
            buildRows()
                .filter((row) => rowMatchesFilters(row, { ...DEFAULT_TABLES_FILTERS, ...filters }))
                .map((row) => row.name)
        ).toEqual(expectedNames)
    })

    it.each<[TablesSort, string[]]>([
        [
            { column: 'name', direction: 'asc' },
            ['deleted_view', 'events', 'orders_daily', 'orders_export', 'revenue', 'sessions', 'stripe.charges'],
        ],
        [
            { column: 'status', direction: 'asc' },
            ['revenue', 'events', 'deleted_view', 'orders_daily', 'orders_export', 'sessions', 'stripe.charges'],
        ],
        [
            { column: 'checks', direction: 'desc' },
            ['deleted_view', 'stripe.charges', 'events', 'orders_daily', 'orders_export', 'revenue', 'sessions'],
        ],
        [
            { column: 'trust', direction: 'asc' },
            ['stripe.charges', 'orders_daily', 'deleted_view', 'events', 'orders_export', 'revenue', 'sessions'],
        ],
        [
            { column: 'refresh', direction: 'desc' },
            ['stripe.charges', 'revenue', 'deleted_view', 'events', 'orders_daily', 'orders_export', 'sessions'],
        ],
    ])('sorting by %j orders rows %j, empty values last', (sort, expectedNames) => {
        expect(sortCatalogTableRows(buildRows(), sort).map((row) => row.name)).toEqual(expectedNames)
    })

    it('matches a PostHog table to its checks by name while its subject id is unknown', () => {
        const events = buildRows({ posthogTableSubjectIds: {} }).filter((row) => row.name === 'events')

        expect(events.map((row) => ({ key: row.key, checks: row.checkCounts.total }))).toEqual([
            { key: 'posthog:events', checks: 1 },
        ])
    })

    it('lists managed views and counts checks from the health rollup when check rows are missing', () => {
        const rows = buildRows({
            managedViews: [
                { type: 'managed_view', id: 'managed-mrr', name: 'revenue_analytics.mrr', fields: {} },
            ] as unknown as DatabaseSchemaManagedViewTable[],
            healthBySubjectKey: {
                'view:query-orders': {
                    subject_type: 'view',
                    subject_uuid: 'query-orders',
                    health: 'failing',
                    checks_total: 4,
                    checks_failing: 1,
                },
            },
        })

        expect(
            rows
                .filter((row) => ['revenue_analytics.mrr', 'orders_daily'].includes(row.name))
                .map((row) => ({ name: row.name, subtitle: row.subtitle, checks: row.checkCounts }))
        ).toEqual([
            { name: 'orders_daily', subtitle: 'View', checks: { total: 4, failing: 1 } },
            { name: 'revenue_analytics.mrr', subtitle: 'Managed view', checks: { total: 0, failing: 0 } },
        ])
    })
})
