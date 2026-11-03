import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingNode } from '~/types'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { lineageDataLogic } from './lineage/lineageDataLogic'
import { modelsListLogic } from './modelsListLogic'
import { viewsTabLogic } from './viewsTabLogic'

const NODES_URL = '/api/environments/:team_id/data_modeling_nodes/'
const CHECKS_URL = '/api/projects/:team_id/data_quality_checks/'
const RUN_HISTORY_URL = '/api/environments/:team_id/warehouse_saved_queries/:id/run_history/'

function buildNode(id: string, overrides: Partial<DataModelingNode> = {}): DataModelingNode {
    return {
        id,
        name: id,
        type: 'matview',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        upstream_count: 0,
        downstream_count: 0,
        saved_query_id: `query-${id}`,
        last_run_status: 'Completed',
        ...overrides,
    }
}

function buildSavedQueries(nodes: DataModelingNode[]): Record<string, unknown> {
    const results = nodes.map((node) => ({
        id: node.saved_query_id,
        name: node.name,
        columns: [],
        is_materialized: node.type !== 'view',
    }))
    return { count: results.length, results }
}

const HEALTHY_NODES = Array.from({ length: 12 }, (_, index) => buildNode(`healthy-${index + 1}`))
const PROBLEM_NODES = [
    buildNode('broken', { last_run_status: 'Failed', last_run_error: 'boom' }),
    buildNode('checked', { type: 'view' }),
]
const FAILING_CHECKS = [
    { subject_type: 'view', subject_name: 'checked', subject_node_id: 'checked' },
    { subject_type: 'posthog_table', subject_name: 'events', subject_node_id: null },
].map((subject, index) => ({
    id: `check-${index}`,
    name: `check-${index}`,
    check_type: 'not_null',
    last_status: 'failed',
    ...subject,
}))

describe('modelsListLogic', () => {
    let logic: ReturnType<typeof modelsListLogic.build>
    let runHistoryRequests: string[]

    function apiMocks(nodes: DataModelingNode[], checks: Record<string, unknown>[]): Parameters<typeof useMocks>[0] {
        const savedQueries = buildSavedQueries(nodes)
        return {
            get: {
                [NODES_URL]: { count: nodes.length, results: nodes },
                '/api/environments/:team_id/data_modeling_edges/': { count: 0, results: [] },
                '/api/environments/:team_id/warehouse_saved_queries/': savedQueries,
                '/api/projects/:team_id/warehouse_saved_queries/': savedQueries,
                [CHECKS_URL]: { count: checks.length, results: checks },
                '/api/projects/:team_id/data_quality_checks/health/': [],
                '/api/projects/:team_id/data_quality_checks/schedules/': [],
                [RUN_HISTORY_URL]: (request) => {
                    runHistoryRequests.push(request.params.id as string)
                    return [200, { run_history: [{ status: 'Completed', timestamp: '2026-01-01T00:00:00Z' }] }]
                },
            },
        }
    }

    async function mountLoaded(): Promise<void> {
        router.actions.push(urls.models())
        logic = modelsListLogic()
        logic.mount()
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess', 'loadEdgesSuccess'])
        await expectLogic(dataWarehouseViewsLogic).toDispatchActions(['loadDataWarehouseSavedQueriesSuccess'])
        await expectLogic(dataQualityOverviewLogic).toDispatchActions(['loadOverviewSuccess'])
    }

    beforeEach(() => {
        runHistoryRequests = []
        jest.spyOn(Date, 'now').mockReturnValue(new Date('2026-01-01T12:00:00Z').getTime())
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it.each<[string, DataModelingNode[], string, string[]]>([
        [
            'opens on the models that need attention, and leaves table checks to the catalog',
            [...HEALTHY_NODES, ...PROBLEM_NODES],
            'attention',
            ['query-broken', 'query-checked'],
        ],
        [
            'opens on every model when nothing needs attention',
            HEALTHY_NODES.slice(0, 2),
            'all',
            ['query-healthy-1', 'query-healthy-2'],
        ],
    ])('%s', async (_case, nodes, expectedFilter, expectedRows) => {
        useMocks(apiMocks(nodes, FAILING_CHECKS))
        await mountLoaded()

        expect(logic.values.activeHealthFilter).toEqual(expectedFilter)
        expect(logic.values.filteredRows.map(({ view }) => view.id)).toEqual(expectedRows)
        expect(logic.values.allModelRows).toHaveLength(nodes.length)
    })

    it('keeps the chosen page when models reload, and loads run history for that page only', async () => {
        useMocks(apiMocks(HEALTHY_NODES, []))
        await mountLoaded()

        await expectLogic(viewsTabLogic, () => logic.actions.setPage(2)).toDispatchActions([
            (action) =>
                action.type === viewsTabLogic.actionTypes.loadRunHistorySuccess &&
                'query-healthy-11' in action.payload.runHistoryMap,
        ])
        await expectLogic(lineageDataLogic, () => lineageDataLogic.actions.loadNodes()).toDispatchActions([
            'loadNodesSuccess',
        ])

        expect(logic.values.currentPage).toEqual(2)
        expect(logic.values.visibleRows.map(({ view }) => view.id)).toEqual(['query-healthy-11', 'query-healthy-12'])
        expect(runHistoryRequests.sort()).toEqual(HEALTHY_NODES.map((node) => node.saved_query_id).sort())
    })
})
