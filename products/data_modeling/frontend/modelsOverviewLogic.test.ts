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

function buildCheck(id: string, lastStatus: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        id,
        name: id,
        check_type: 'not_null',
        subject_type: 'posthog_table',
        subject_name: 'events',
        last_status: lastStatus,
        ...overrides,
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

    it('lists each view or table once, with its materialization problem and its failing checks together', async () => {
        useMocks(
            apiMocks(NODES, [
                buildCheck('nulls', 'failed'),
                buildCheck('ok', 'passed'),
                buildCheck('late-rows', 'errored', {
                    subject_type: 'view',
                    subject_name: 'late',
                    subject_node_id: 'late',
                }),
            ])
        )
        await mountLoaded()

        expect(
            logic.values.attentionSubjects.map(({ key, materialization, failingChecks }) => [
                key,
                materialization?.kind ?? null,
                failingChecks.map(({ id }) => id),
            ])
        ).toEqual([
            ['view-query-paused', 'suspended', []],
            ['view-query-broken', 'failed', []],
            ['view-query-late', 'behind', ['late-rows']],
            ['posthog_table-events', null, ['nulls']],
        ])
    })

    it('puts a check on another node of the same view in the same row as the view', async () => {
        useMocks(
            apiMocks(NODES, [
                buildCheck('broken-rows', 'failed', {
                    subject_type: 'view',
                    subject_uuid: 'query-broken',
                    subject_name: 'broken',
                    subject_node_id: 'broken-in-second-dag',
                }),
            ])
        )
        await mountLoaded()

        expect(
            logic.values.attentionSubjects
                .filter(({ key }) => key === 'view-query-broken')
                .map(({ materialization, failingChecks }) => [
                    materialization?.kind ?? null,
                    failingChecks.map(({ id }) => id),
                ])
        ).toEqual([['failed', ['broken-rows']]])
    })

    it('keeps one row for a table whose checks carry an old and a new name', async () => {
        useMocks(
            apiMocks(NODES, [
                buildCheck('old-name', 'failed', { subject_type: 'table', subject_uuid: 't1', subject_name: 'orders' }),
                buildCheck('new-name', 'failed', {
                    subject_type: 'table',
                    subject_uuid: 't1',
                    subject_name: 'orders_v2',
                }),
            ])
        )
        await mountLoaded()

        expect(logic.values.attentionSubjects.at(-1)?.failingChecks.map(({ id }) => id)).toEqual([
            'old-name',
            'new-name',
        ])
    })

    it('narrows the table to one problem, and shows every row again once that problem is gone', async () => {
        await mountLoaded()

        logic.actions.setAttentionFilter('failed')
        expect(logic.values.filteredAttentionSubjects.map(({ key }) => key)).toEqual(['view-query-broken'])

        useMocks({
            get: {
                [NODES_URL]: {
                    count: NODES.length,
                    results: NODES.map((node) =>
                        node.id === 'broken' ? { ...node, last_run_status: 'Running' } : node
                    ),
                },
            },
        })
        await expectLogic(lineageDataLogic, () => logic.actions.loadNodes()).toDispatchActions(['loadNodesSuccess'])

        expect(logic.values.activeAttentionFilter).toEqual('all')
        expect(logic.values.filteredAttentionSubjects).toHaveLength(3)
    })

    it.each<[string, number, string[]]>([
        ['keeps the button disabled after a refresh starts', 200, ['query-broken']],
        ['re-enables the button when the refresh fails to start', 500, []],
    ])('%s', async (_case, status, expectedStarted) => {
        useMocks({
            post: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/run/': () => [status, {}],
                '/api/projects/:team_id/warehouse_saved_queries/:id/run/': () => [status, {}],
            },
        })
        await mountLoaded()

        await expectLogic(logic, () => logic.actions.runDataWarehouseSavedQuery('query-broken')).toDispatchActions([
            status === 200 ? 'runDataWarehouseSavedQuerySuccess' : 'runDataWarehouseSavedQueryFailure',
        ])

        expect(logic.values.startedRefreshSavedQueryIds).toEqual(expectedStarted)
    })

    it.each<[string, string, boolean]>([
        ['re-enables the button when the run fails', 'Failed', true],
        ['drops the row when the run succeeds', 'Completed', false],
    ])('after a refresh starts, %s', async (_case, finalStatus, rowStays) => {
        const nodesWithBrokenStatus = (status: string): Parameters<typeof useMocks>[0] => ({
            get: {
                [NODES_URL]: {
                    count: NODES.length,
                    results: NODES.map((node) => (node.id === 'broken' ? { ...node, last_run_status: status } : node)),
                },
            },
        })
        useMocks({
            post: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/run/': () => [200, {}],
                '/api/projects/:team_id/warehouse_saved_queries/:id/run/': () => [200, {}],
            },
        })
        await mountLoaded()

        useMocks(nodesWithBrokenStatus('Running'))
        await expectLogic(logic, () => logic.actions.runDataWarehouseSavedQuery('query-broken')).toDispatchActions([
            'runDataWarehouseSavedQuerySuccess',
            'loadNodesSuccess',
        ])
        expect(logic.values.startedRefreshSavedQueryIds).toEqual(['query-broken'])

        useMocks(nodesWithBrokenStatus(finalStatus))
        await expectLogic(logic, () => logic.actions.loadNodes()).toDispatchActions([
            'loadNodesSuccess',
            'settleRefresh',
        ])

        expect(logic.values.startedRefreshSavedQueryIds).toEqual([])
        expect(logic.values.attentionSubjects.some(({ key }) => key === 'view-query-broken')).toBe(rowStays)
    })

    it('never reports a healthy overview when checks fail to load', async () => {
        useMocks({ get: { [CHECKS_URL]: () => [500, {}] } })
        router.actions.push(urls.models())
        logic = modelsOverviewLogic()
        logic.mount()
        await expectLogic(dataQualityOverviewLogic).toDispatchActions(['loadOverviewFailure'])
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess'])

        expect(logic.values.nothingToReport).toBe(false)
    })

    it('keeps the rows on screen while models reload', async () => {
        await mountLoaded()

        lineageDataLogic.actions.loadNodes()

        expect(logic.values.modelsFirstLoading).toBe(false)
        expect(logic.values.attentionSubjects).toHaveLength(4)
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
