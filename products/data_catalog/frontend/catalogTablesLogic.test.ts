import { waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TABLES_PAGE_SIZE, catalogTablesLogic } from './catalogTablesLogic'

const VIEW_COUNT = 21
const viewIds = Array.from({ length: VIEW_COUNT }, (_, index) => `query-${String(index + 1).padStart(2, '0')}`)
const lastViewId = viewIds[VIEW_COUNT - 1]

const databaseTables = Object.fromEntries(
    viewIds.map((id) => [
        `view_${id}`,
        { type: 'view', id, name: `view_${id}`, fields: {}, query: { kind: 'HogQLQuery', query: 'select 1' } },
    ])
)

const savedQueries = viewIds.map((id) => ({
    id,
    name: `view_${id}`,
    columns: [],
    is_materialized: true,
    origin: 'data_warehouse',
    managed_viewset_kind: null,
}))

const failingCheckOnLastView = {
    id: 'check-last',
    name: 'row count',
    check_type: 'row_count',
    subject_type: 'view',
    subject_uuid: lastViewId,
    subject_name: `view_${lastViewId}`,
    subject_node_id: null,
    last_status: 'failed',
}

describe('catalogTablesLogic', () => {
    let logic: ReturnType<typeof catalogTablesLogic.build>
    let releaseChecks: () => void
    let runHistoryRequests: string[]

    beforeEach(() => {
        runHistoryRequests = []
        const checksReady = new Promise<void>((resolve) => {
            releaseChecks = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/data_quality_checks/': async () => {
                    await checksReady
                    return [200, { results: [failingCheckOnLastView], count: 1 }]
                },
                '/api/projects/:team_id/data_quality_checks/health/': [],
                '/api/projects/:team_id/data_quality_checks/schedules/': [],
                '/api/projects/:team_id/data_quality_checks/subjects/': [],
                '/api/projects/:team_id/data_catalog/certifications/': { results: [], count: 0 },
                '/api/environments/:team_id/data_modeling_nodes/': { results: [], count: 0 },
                '/api/environments/:team_id/data_modeling_edges/': { results: [], count: 0 },
                '/api/environments/:team_id/warehouse_saved_queries/': {
                    results: savedQueries,
                    count: savedQueries.length,
                },
                '/api/environments/:team_id/warehouse_saved_queries/:id/run_history/': ({ params }) => {
                    runHistoryRequests.push(params.id as string)
                    return [200, { run_history: [] }]
                },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': { tables: databaseTables, joins: [] },
            },
        })
        initKeaTests()
        logic = catalogTablesLogic()
        logic.mount()
    })

    afterEach(() => {
        releaseChecks()
        logic.unmount()
    })

    it('loads run history for a view that moves onto the first page when its failing check arrives last', async () => {
        await waitFor(() => expect(runHistoryRequests).toHaveLength(TABLES_PAGE_SIZE))
        expect(runHistoryRequests).not.toContain(lastViewId)

        releaseChecks()

        await waitFor(() => expect(runHistoryRequests).toContain(lastViewId))
        expect(logic.values.visibleRows[0].key).toEqual(`view:${lastViewId}`)
    })
})
