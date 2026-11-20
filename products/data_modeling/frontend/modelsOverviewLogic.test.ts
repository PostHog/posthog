import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingNode } from '~/types'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { lineageDataLogic } from './lineage/lineageDataLogic'
import { AttentionRow, modelsOverviewLogic } from './modelsOverviewLogic'

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
    buildNode('broken', { last_run_status: 'Failed', last_run_error: 'boom', last_run_at: '2026-01-01T10:00:00Z' }),
    buildNode('paused', {
        last_run_status: 'Failed',
        suspended: { clickhouse: { at: '2026-01-02T00:00:00Z', reason: 'stopped', job_id: 'j1' } },
    }),
    buildNode('late', { last_run_status: 'Completed', sync_interval: '1hour', last_run_at: '2026-01-01T00:00:00Z' }),
    buildNode('plain-view', { type: 'view' }),
    buildNode('endpoint', { type: 'endpoint', last_run_status: 'Completed' }),
    buildNode('broken-in-second-dag', { saved_query_id: 'query-broken', last_run_status: 'Completed' }),
]
function plainText(text: string): string {
    return text.replace(/\u00a0/g, ' ')
}

const SAVED_QUERIES = { count: 3, results: ['a', 'b', 'c'].map((id) => ({ id, name: id, columns: [] })) }

describe('modelsOverviewLogic', () => {
    let logic: ReturnType<typeof modelsOverviewLogic.build>

    function apiMocks(
        nodes: DataModelingNode[],
        checks: Record<string, unknown>[],
        savedQueries = SAVED_QUERIES,
        health: Record<string, unknown>[] = []
    ): Parameters<typeof useMocks>[0] {
        return {
            get: {
                [NODES_URL]: { count: nodes.length, results: nodes },
                '/api/environments/:team_id/data_modeling_edges/': { count: 0, results: [] },
                '/api/environments/:team_id/warehouse_saved_queries/': savedQueries,
                '/api/projects/:team_id/warehouse_saved_queries/': savedQueries,
                [CHECKS_URL]: { count: checks.length, results: checks },
                '/api/projects/:team_id/data_quality_checks/health/': health,
                '/api/projects/:team_id/data_quality_checks/schedules/': [],
            },
        }
    }

    function nodesWithLate(overrides: Partial<DataModelingNode>): Parameters<typeof useMocks>[0] {
        return {
            get: {
                [NODES_URL]: {
                    count: NODES.length,
                    results: NODES.map((node) => (node.id === 'late' ? { ...node, ...overrides } : node)),
                },
            },
        }
    }

    function runMock(status: number): { calls: number; mocks: Parameters<typeof useMocks>[0] } {
        const tracker = { calls: 0, mocks: {} as Parameters<typeof useMocks>[0] }
        tracker.mocks = {
            post: {
                '/api/projects/:team_id/warehouse_saved_queries/:id/run/': () => {
                    tracker.calls += 1
                    return [status, { node_ids: [] }]
                },
            },
        }
        return tracker
    }

    function lateRow(): AttentionRow | undefined {
        return logic.values.attentionRows.find(({ key }) => key === 'view-query-late')
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
        expect(logic.values.filteredAttentionRows.map(({ key }) => key)).toEqual(['view-query-broken'])

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
        expect(logic.values.filteredAttentionRows).toHaveLength(3)
    })

    it('builds each row with the copy and next step its cells render', async () => {
        await mountLoaded()

        expect(
            logic.values.attentionRows.map(({ name, statuses, detail, since, nextStep }) => ({
                name,
                labels: statuses.map(({ label }) => plainText(label)),
                detail,
                since: since?.label ?? null,
                nextStep: nextStep?.kind === 'refresh' ? 'Refresh' : (nextStep?.label ?? null),
            }))
        ).toEqual([
            { name: 'paused', labels: ['Suspended'], detail: 'stopped', since: null, nextStep: 'Open view' },
            { name: 'broken', labels: ['Refresh failed'], detail: 'boom', since: 'Last tried', nextStep: 'Refresh' },
            {
                name: 'late',
                labels: ['Behind schedule'],
                detail: 'Should refresh every 1 hour',
                since: '11h behind schedule',
                nextStep: 'Refresh',
            },
            { name: 'events', labels: ['1 check failing'], detail: 'nulls', since: null, nextStep: null },
        ])
    })

    it('reads the cadence a model inherits from a view downstream of it', async () => {
        useMocks(
            apiMocks(
                [
                    buildNode('inherited', {
                        last_run_status: 'Completed',
                        sync_interval: '24hour',
                        effective_sync_interval: '1hour',
                        last_run_at: '2026-01-01T09:00:00Z',
                    }),
                ],
                []
            )
        )
        await mountLoaded()

        expect(logic.values.attentionRows.map(({ detail }) => detail)).toEqual(['Should refresh every 1 hour'])
    })

    it('shows a refresh as running from the request until the node finishes, then drops the row', async () => {
        const run = runMock(200)
        useMocks(run.mocks)
        await mountLoaded()

        await expectLogic(logic, () => logic.actions.requestRefresh('query-late')).toDispatchActions([
            'loadNodesSuccess',
        ])
        expect(Object.keys(logic.values.refreshRequests)).toEqual(['query-late'])
        expect(lateRow()?.nextStep).toEqual({ kind: 'refresh', savedQueryId: 'query-late', refreshing: true })

        useMocks(nodesWithLate({ last_run_status: 'Running' }))
        await expectLogic(logic, () => logic.actions.loadNodes()).toDispatchActions([
            'loadNodesSuccess',
            'clearRefreshRequests',
        ])
        expect(logic.values.refreshRequests).toEqual({})
        expect(lateRow()?.nextStep).toEqual({ kind: 'refresh', savedQueryId: 'query-late', refreshing: true })

        useMocks(nodesWithLate({ last_run_status: 'Completed', last_run_at: '2026-01-01T11:59:00Z' }))
        await expectLogic(logic, () => logic.actions.loadNodes()).toDispatchActions(['loadNodesSuccess'])
        expect(lateRow()).toBeUndefined()
    })

    it('frees the button when the refresh request fails', async () => {
        const run = runMock(500)
        useMocks(run.mocks)
        await mountLoaded()

        await expectLogic(logic, () => logic.actions.requestRefresh('query-late')).toDispatchActions([
            'refreshRequestFailed',
        ])

        expect(logic.values.refreshRequests).toEqual({})
        expect(lateRow()?.nextStep).toEqual({ kind: 'refresh', savedQueryId: 'query-late', refreshing: false })
    })

    it('sends one refresh request when the button is pressed twice', async () => {
        const run = runMock(200)
        useMocks(run.mocks)
        await mountLoaded()

        logic.actions.requestRefresh('query-late')
        await expectLogic(logic, () => logic.actions.requestRefresh('query-late')).toDispatchActions([
            'loadNodesSuccess',
        ])

        expect(run.calls).toEqual(1)
    })

    it('counts failing checks from the health rollup, including subjects past the loaded check rows', async () => {
        useMocks(
            apiMocks(NODES, [buildCheck('nulls', 'failed', { subject_uuid: 'events-id' })], SAVED_QUERIES, [
                {
                    subject_type: 'posthog_table',
                    subject_uuid: 'events-id',
                    health: 'failing',
                    checks_total: 4,
                    checks_failing: 3,
                },
                {
                    subject_type: 'table',
                    subject_uuid: 'orders-id',
                    health: 'failing',
                    checks_total: 2,
                    checks_failing: 1,
                },
            ])
        )
        await mountLoaded()

        expect(logic.values.attentionRows.at(-1)?.statuses.map(({ label }) => plainText(label))).toEqual([
            '3 checks failing',
        ])
        expect(logic.values.unlistedFailingSubjectCount).toEqual(1)
        expect(logic.values.attentionCounts).toMatchObject({ all: 5, checks: 2 })
    })

    it.each<[string, Record<string, unknown>[], boolean]>([
        ['nothing in the rollup is failing', [], true],
        [
            'a subject outside the loaded check rows is failing',
            [
                {
                    subject_type: 'table',
                    subject_uuid: 'orders-id',
                    health: 'failing',
                    checks_total: 2,
                    checks_failing: 1,
                },
            ],
            false,
        ],
    ])('reports a healthy overview only when %s', async (_case, health, expected) => {
        const healthyNodes = NODES.filter((node) => ['plain-view', 'endpoint'].includes(node.id))
        useMocks(apiMocks(healthyNodes, [buildCheck('ok', 'passed')], SAVED_QUERIES, health))
        await mountLoaded()

        expect(logic.values.nothingToReport).toBe(expected)
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
        expect(logic.values.attentionRows).toHaveLength(4)
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
