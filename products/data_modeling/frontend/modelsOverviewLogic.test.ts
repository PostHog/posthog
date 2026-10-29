import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingNode } from '~/types'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { lineageDataLogic } from './lineage/lineageDataLogic'
import { modelsOverviewLogic } from './modelsOverviewLogic'

const NODES_URL = '/api/environments/:team_id/data_modeling_nodes/'
const CHECKS_URL = '/api/projects/:team_id/data_quality_checks/'

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
        ...overrides,
    }
}

function buildCheck(id: string, lastStatus: string): Record<string, unknown> {
    return {
        id,
        name: id,
        check_type: 'not_null',
        subject_type: 'posthog_table',
        subject_name: 'events',
        last_status: lastStatus,
    }
}

const NODES = [
    buildNode('broken', { last_run_status: 'Failed', last_run_error: 'boom' }),
    buildNode('paused', {
        last_run_status: 'Failed',
        suspended: { clickhouse: { at: '2026-01-02T00:00:00Z', reason: 'stopped', job_id: 'j1' } },
    }),
    buildNode('late', { last_run_status: 'Completed', sync_interval: '1hour', last_run_at: '2026-01-01T00:00:00Z' }),
    buildNode('plain-view', { type: 'view' }),
    buildNode('endpoint', { type: 'endpoint', last_run_status: 'Completed' }),
    buildNode('broken-in-second-dag', { saved_query_id: 'query-broken', last_run_status: 'Completed' }),
]
const SAVED_QUERIES = { count: 3, results: ['a', 'b', 'c'].map((id) => ({ id, name: id, columns: [] })) }

describe('modelsOverviewLogic', () => {
    let logic: ReturnType<typeof modelsOverviewLogic.build>

    function apiMocks(
        nodes: DataModelingNode[],
        checks: Record<string, unknown>[],
        savedQueries = SAVED_QUERIES
    ): Parameters<typeof useMocks>[0] {
        return {
            get: {
                [NODES_URL]: { count: nodes.length, results: nodes },
                '/api/environments/:team_id/data_modeling_edges/': { count: 0, results: [] },
                '/api/environments/:team_id/warehouse_saved_queries/': savedQueries,
                '/api/projects/:team_id/warehouse_saved_queries/': savedQueries,
                [CHECKS_URL]: { count: checks.length, results: checks },
                '/api/projects/:team_id/data_quality_checks/health/': [],
                '/api/projects/:team_id/data_quality_checks/schedules/': [],
            },
        }
    }

    async function mountLoaded(): Promise<void> {
        router.actions.push(urls.models())
        logic = modelsOverviewLogic()
        logic.mount()
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess', 'loadEdgesSuccess'])
        await expectLogic(dataWarehouseViewsLogic).toDispatchActions(['loadDataWarehouseSavedQueriesSuccess'])
        await expectLogic(dataQualityOverviewLogic).toDispatchActions(['loadOverviewSuccess'])
    }

    beforeEach(() => {
        jest.spyOn(Date, 'now').mockReturnValue(new Date('2026-01-01T12:00:00Z').getTime())
        useMocks(apiMocks(NODES, [buildCheck('nulls', 'failed'), buildCheck('ok', 'passed')]))
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('puts suspended, failed and late models under materialization and failing checks under data quality, counted the same as the stats', async () => {
        await mountLoaded()

        expect(logic.values.materializationIssues.map(({ kind, key }) => [kind, key])).toEqual([
            ['suspended', 'model-paused'],
            ['failed', 'model-broken'],
            ['behind', 'behind-late'],
        ])
        expect(logic.values.checkIssues.map(({ key }) => key)).toEqual(['check-nulls'])
        expect(logic.values.overviewStats).toMatchObject({ materializationIssues: 3, failingChecks: 1 })
    })

    it('counts saved queries past the first page and each materialized view or endpoint once across DAGs', async () => {
        useMocks(apiMocks(NODES, [], { ...SAVED_QUERIES, count: 1003 }))
        await mountLoaded()

        expect(logic.values.overviewStats).toMatchObject({ models: 1003, materialized: 4 })
    })

    it('reports failing checks as unknown, not zero, when checks fail to load', async () => {
        useMocks({ get: { [CHECKS_URL]: () => [500, {}] } })
        router.actions.push(urls.models())
        logic = modelsOverviewLogic()
        logic.mount()
        await expectLogic(dataQualityOverviewLogic).toDispatchActions(['loadOverviewFailure'])
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess'])

        expect(logic.values.overviewStats.failingChecks).toBeNull()
        expect(logic.values.nothingToReport).toBe(false)
    })

    it('keeps the counts on screen while models reload', async () => {
        await mountLoaded()

        lineageDataLogic.actions.loadNodes()

        expect(logic.values.modelsFirstLoading).toBe(false)
        expect(logic.values.overviewStats.models).toEqual(3)
    })

    it.each<[string, Record<string, unknown>[], boolean]>([
        ['shows the first view when nothing else needs reporting', [], true],
        ['keeps failing table checks visible instead of the first view', [buildCheck('nulls', 'failed')], false],
    ])('in a project with no models, %s', async (_case, checks, expected) => {
        useMocks(apiMocks([], checks, { count: 0, results: [] }))

        await mountLoaded()

        expect(logic.values.showFirstView).toBe(expected)
    })
})
