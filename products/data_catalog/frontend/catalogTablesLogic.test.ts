import { MOCK_TEAM_ID } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import type { Mocks } from '~/mocks/utils'
import { initKeaTests } from '~/test/init'

import { TABLES_PAGE_SIZE, catalogTablesLogic } from './catalogTablesLogic'
import { catalogDataQualityLogic } from './dataQuality/catalogDataQualityLogic'

type MockGetHandler = Mocks['get'] extends Record<string, infer Handler> | undefined ? Handler : never

function catalogMocks({
    tables,
    savedQueries = [],
    checks,
    certifications = [],
    extra = {},
}: {
    tables: Record<string, unknown>
    savedQueries?: Record<string, unknown>[]
    checks: MockGetHandler
    certifications?: Record<string, unknown>[]
    extra?: Mocks
}): Mocks {
    return {
        get: {
            '/api/projects/:team_id/data_quality_checks/': checks,
            '/api/projects/:team_id/data_quality_checks/health/': [],
            '/api/projects/:team_id/data_quality_checks/schedules/': [],
            '/api/projects/:team_id/data_quality_checks/subjects/': [],
            '/api/projects/:team_id/data_catalog/certifications/': {
                results: certifications,
                count: certifications.length,
            },
            '/api/projects/:team_id/data_modeling_nodes/': { results: [], count: 0 },
            '/api/projects/:team_id/data_modeling_edges/': { results: [], count: 0 },
            '/api/projects/:team_id/warehouse_saved_queries/': {
                results: savedQueries,
                count: savedQueries.length,
            },
            ...extra.get,
        },
        post: {
            '/api/projects/:team_id/query/:query_kind/': { tables, joins: [] },
            ...extra.post,
        },
        delete: { ...extra.delete },
    }
}

function check(id: string, subjectUuid: string, subjectName: string, lastStatus: string): Record<string, unknown> {
    return {
        id,
        name: id,
        check_type: 'row_count',
        subject_type: 'table',
        subject_uuid: subjectUuid,
        subject_name: subjectName,
        subject_node_id: null,
        last_status: lastStatus,
    }
}

describe('catalogTablesLogic', () => {
    let logic: ReturnType<typeof catalogTablesLogic.build>

    afterEach(() => {
        logic.unmount()
    })

    describe('run history', () => {
        const VIEW_COUNT = 21
        const viewIds = Array.from({ length: VIEW_COUNT }, (_, index) => `query-${String(index + 1).padStart(2, '0')}`)
        const lastViewId = viewIds[VIEW_COUNT - 1]
        let releaseChecks: () => void
        let runHistoryRequests: string[]

        beforeEach(() => {
            runHistoryRequests = []
            const checksReady = new Promise<void>((resolve) => {
                releaseChecks = resolve
            })
            useMocks(
                catalogMocks({
                    tables: Object.fromEntries(
                        viewIds.map((id) => [
                            `view_${id}`,
                            {
                                type: 'view',
                                id,
                                name: `view_${id}`,
                                fields: {},
                                query: { kind: 'HogQLQuery', query: 'select 1' },
                            },
                        ])
                    ),
                    savedQueries: viewIds.map((id) => ({
                        id,
                        name: `view_${id}`,
                        columns: [],
                        is_materialized: true,
                        origin: 'data_warehouse',
                        managed_viewset_kind: null,
                    })),
                    checks: async () => {
                        await checksReady
                        return [
                            200,
                            {
                                results: [
                                    {
                                        ...check('check-last', lastViewId, `view_${lastViewId}`, 'failed'),
                                        subject_type: 'view',
                                    },
                                ],
                                count: 1,
                            },
                        ]
                    },
                    extra: {
                        get: {
                            '/api/projects/:team_id/warehouse_saved_queries/:id/run_history/': ({ params }) => {
                                runHistoryRequests.push(params.id as string)
                                return [200, { run_history: [] }]
                            },
                        },
                    },
                })
            )
            initKeaTests()
            logic = catalogTablesLogic()
            logic.mount()
        })

        afterEach(() => {
            releaseChecks()
        })

        it('loads run history for a view that moves onto the first page when its failing check arrives last', async () => {
            await waitFor(() => expect(runHistoryRequests).toHaveLength(TABLES_PAGE_SIZE))
            expect(runHistoryRequests).not.toContain(lastViewId)

            releaseChecks()

            await waitFor(() => expect(runHistoryRequests).toContain(lastViewId))
            expect(logic.values.visibleRows[0].key).toEqual(`view:${lastViewId}`)
        })
    })

    describe('schema load', () => {
        it('requests the schema without columns, because the tables list reads none', async () => {
            const schemaQueries: Record<string, unknown>[] = []
            useMocks(
                catalogMocks({
                    tables: {},
                    checks: { results: [], count: 0 },
                    extra: {
                        post: {
                            '/api/projects/:team_id/query/:query_kind/': async ({ request }) => {
                                const body = (await request.json()) as { query: Record<string, unknown> }
                                schemaQueries.push(body.query)
                                return [200, { tables: {}, joins: [] }]
                            },
                        },
                    },
                })
            )
            initKeaTests()
            logic = catalogTablesLogic()
            logic.mount()

            await waitFor(() => expect(logic.values.rowsLoaded).toBe(true))
            expect(schemaQueries.length).toBeGreaterThan(0)
            expect(new Set(schemaQueries.map((query) => query.includeFields))).toEqual(new Set([false]))
        })
    })

    describe('proposal review', () => {
        const sourceTable = (id: string, name: string): Record<string, unknown> => ({
            type: 'data_warehouse',
            id,
            name,
            fields: {},
            format: 'Parquet',
            url_pattern: '',
            source: { id: 'source-1', source_type: 'Stripe', status: 'Completed', prefix: '' },
            schema: { id: `schema-${id}`, name, should_sync: true, incremental: true, last_synced_at: null },
        })
        const proposal = (id: string, tableId: string, proposedStatus: string): Record<string, unknown> => ({
            id,
            table: tableId,
            saved_query: null,
            target_type: 'table',
            target_name: tableId,
            status: 'proposed',
            proposed_status: proposedStatus,
            notes: '',
            certified_by: null,
            certified_at: null,
            created_by: null,
            created_at: '2026-11-01T00:00:00Z',
        })
        let reviewRequests: string[]
        let schemaQueries: Record<string, unknown>[]

        beforeEach(async () => {
            reviewRequests = []
            schemaQueries = []
            const tables = {
                'stripe.charges': sourceTable('table-charges', 'stripe.charges'),
                'stripe.refunds': sourceTable('table-refunds', 'stripe.refunds'),
                'stripe.customers': sourceTable('table-customers', 'stripe.customers'),
            }
            const proposals = [
                proposal('cert-charges', 'table-charges', 'certified'),
                proposal('cert-refunds', 'table-refunds', 'deprecated'),
            ]
            const record =
                (verb: string, status: string) =>
                ({ params }: { params: Record<string, unknown> }): [number, Record<string, unknown>] => {
                    reviewRequests.push(`${verb}:${params.id as string}`)
                    return [200, { ...proposals.find((entry) => entry.id === params.id), status }]
                }
            useMocks(
                catalogMocks({
                    tables,
                    checks: {
                        results: [
                            check('charges-check', 'table-charges', 'stripe.charges', 'passed'),
                            { ...check('mrr-check', 'metric-mrr', 'mrr', 'failed'), subject_type: 'metric' },
                        ],
                        count: 2,
                    },
                    certifications: proposals,
                    extra: {
                        post: {
                            '/api/projects/:team_id/query/:query_kind/': async ({ request }) => {
                                const body = (await request.json()) as { query: Record<string, unknown> }
                                schemaQueries.push(body.query)
                                return [200, { tables, joins: [] }]
                            },
                            '/api/projects/:team_id/data_catalog/certifications/:id/certify/': record(
                                'certify',
                                'certified'
                            ),
                            '/api/projects/:team_id/data_catalog/certifications/:id/deprecate/': record(
                                'deprecate',
                                'deprecated'
                            ),
                        },
                        delete: {
                            '/api/projects/:team_id/data_catalog/certifications/:id/': record('reject', 'deleted'),
                        },
                    },
                })
            )
            initKeaTests()
            logic = catalogTablesLogic()
            logic.mount()
            await waitFor(() => {
                if (logic.values.rows.filter((row) => row.certification).length !== 2) {
                    throw new Error('Certifications not loaded yet')
                }
            })
        })

        it.each([
            ['a certification proposal', 'table:table-charges', 'certify:cert-charges', 'Certified stripe.charges'],
            ['a deprecation proposal', 'table:table-refunds', 'deprecate:cert-refunds', 'Deprecated stripe.refunds'],
        ])('accepting %s applies the proposed status', async (_, rowKey, expectedRequest, expectedToast) => {
            const toastSpy = jest.spyOn(lemonToast, 'success')

            logic.actions.reviewProposals([rowKey], 'accept', 'inline')

            await waitFor(() => expect(toastSpy).toHaveBeenCalledWith(expectedToast))
            expect(reviewRequests).toEqual([expectedRequest])
        })

        it('applies a review to the row without waiting for the certifications to reload', async () => {
            const certificationOf = (key: string): string | null =>
                logic.values.rows.find((row) => row.key === key)?.certification?.status ?? null

            logic.actions.reviewProposals(['table:table-refunds'], 'accept', 'inline')
            await waitFor(() => expect(certificationOf('table:table-refunds')).toEqual('deprecated'))

            logic.actions.reviewProposals(['table:table-charges'], 'reject', 'inline')
            await waitFor(() => expect(certificationOf('table:table-charges')).toBeNull())

            await waitFor(() => expect(schemaQueries.length).toBeGreaterThan(1))
            expect(new Set(schemaQueries.map((query) => query.includeFields))).toEqual(new Set([false]))
        })

        it('bulk accept reviews only the selected rows that have a pending proposal', async () => {
            logic.actions.setRowsSelected(['table:table-charges', 'table:table-refunds', 'table:table-customers'], true)
            logic.actions.reviewProposals(
                logic.values.selectedProposalRows.map((row) => row.key),
                'accept',
                'bulk'
            )

            await waitFor(() => expect(logic.values.selectedRowKeys).toEqual([]))
            expect(reviewRequests.sort()).toEqual(['certify:cert-charges', 'deprecate:cert-refunds'])
        })

        it('opens the table when its row is clicked', () => {
            const charges = logic.values.rows.find((row) => row.key === 'table:table-charges')!

            logic.actions.openRow(charges)

            expect(router.values.location.pathname).toEqual(`/project/${MOCK_TEAM_ID}${charges.detailUrl}`)
        })

        it.each([
            [undefined, ['stripe.charges', 'mrr']],
            ['stripe.customers', ['stripe.customers']],
            ['mrr', ['mrr']],
        ])('the data quality section filtered to table %s lists %j', async (table, expectedNames) => {
            router.actions.push(urls.dataCatalog(), { tab: 'data-quality', table })
            const qualityLogic = catalogDataQualityLogic()
            qualityLogic.mount()

            await waitFor(() => expect(qualityLogic.values.checkedRows.map((row) => row.name)).toEqual(expectedNames))
            expect(router.values.searchParams.table).toEqual(table)
            qualityLogic.unmount()
        })
    })
})
