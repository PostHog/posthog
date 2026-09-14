import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingNode } from '~/types'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'

import { modelsSceneLogic } from './modelsSceneLogic'

function buildNode(id: string, overrides: Partial<DataModelingNode> = {}): DataModelingNode {
    return {
        id,
        name: id,
        type: 'matview',
        dag: 'dag-1',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        upstream_count: 0,
        downstream_count: 0,
        saved_query_id: `query-${id}`,
        ...overrides,
    }
}

describe('modelsSceneLogic', () => {
    let logic: ReturnType<typeof modelsSceneLogic.build>

    const mount = async (path: string): Promise<void> => {
        router.actions.push(path)
        logic = modelsSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/': {
                    count: 7,
                    results: [
                        buildNode('healthy', {
                            last_run_status: 'Completed',
                            sync_interval: '1hour',
                            last_run_at: '2024-01-01T00:00:00Z',
                        }),
                        buildNode('broken', {
                            last_run_status: 'Failed',
                            last_run_error: 'Unknown table foo',
                            sync_interval: '1hour',
                            last_run_at: '2024-01-01T00:00:00Z',
                        }),
                        buildNode('child', { last_run_status: 'Skipped' }),
                        buildNode('grandchild', { last_run_status: 'Skipped' }),
                        buildNode('paused', {
                            suspended: { clickhouse: { at: '2024-01-02T00:00:00Z', reason: 'boom', job_id: 'j1' } },
                        }),
                        buildNode('never-ran'),
                        buildNode('shadow-only', {
                            suspended: { duckgres: { at: '2024-01-02T00:00:00Z', reason: 'shadow', job_id: 'j2' } },
                        }),
                    ],
                },
                '/api/environments/:team_id/data_modeling_edges/': {
                    count: 2,
                    results: [
                        { id: 'e1', source_id: 'broken', target_id: 'child', dag: 'dag-1' },
                        { id: 'e2', source_id: 'child', target_id: 'grandchild', dag: 'dag-1' },
                    ],
                },
                '/api/environments/:team_id/warehouse_saved_queries/': {
                    count: 2,
                    results: [
                        { id: 'query-healthy', name: 'healthy', columns: [], is_materialized: true },
                        {
                            id: 'query-broken',
                            name: 'broken',
                            columns: [],
                            is_materialized: true,
                            latest_error: 'a stale copy nothing should read',
                        },
                    ],
                },
            },
        })
        initKeaTests()
    })

    /** Flags outlive a test, so each test that cares states the value it needs. */
    const setFlag = (flag: (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS], value: boolean): void => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(value ? [flag] : [], { [flag]: value })
    }

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['/models', 'overview'],
        ['/models?tab=models', 'models'],
        ['/models?tab=lineage', 'lineage'],
        ['/models?tab=nope', 'overview'],
        ['/models?tab=data-quality', 'overview'],
    ])('%s opens the %s tab', async (path, tab) => {
        await mount(path)
        expect(logic.values.activeTab).toEqual(tab)
    })

    it('opens the data quality tab once its flag is on', async () => {
        setFlag(FEATURE_FLAGS.DATA_QUALITY_CHECKS, true)
        await mount('/models?tab=data-quality')
        expect(logic.values.activeTab).toEqual('data-quality')
    })

    it('opens a data quality deep link after feature flags load', async () => {
        await mount('/models?tab=data-quality')
        expect(logic.values.activeTab).toEqual('overview')

        setFlag(FEATURE_FLAGS.DATA_QUALITY_CHECKS, true)

        expect(logic.values.activeTab).toEqual('data-quality')
    })

    it('counts models whose last run failed and models that are suspended', async () => {
        setFlag(FEATURE_FLAGS.DATA_MODELING_SUSPEND_FAILING_NODES, true)
        await mount('/models')
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess'])
        await expectLogic(dataWarehouseViewsLogic).toDispatchActions(['loadDataWarehouseSavedQueriesSuccess'])

        expect(logic.values.failingNodes.map((node) => node.id)).toEqual(['broken'])
        expect(logic.values.suspendedNodes.map((node) => node.id)).toEqual(['paused'])
    })

    it('ignores a marker on an engine that does not serve queries', async () => {
        setFlag(FEATURE_FLAGS.DATA_MODELING_SUSPEND_FAILING_NODES, true)
        await mount('/models')
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess'])

        // shadow-only carries a duckgres marker. ClickHouse still runs it on schedule.
        expect(logic.values.suspendedNodes.map((node) => node.id)).toEqual(['paused'])
    })

    it('ignores markers on a team that does not enforce suspension', async () => {
        setFlag(FEATURE_FLAGS.DATA_MODELING_SUSPEND_FAILING_NODES, false)
        await mount('/models')
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess'])

        // Detection writes markers for every team, but without enforcement the schedule
        // keeps firing, so the marker records failures rather than a stopped model.
        expect(logic.values.suspendedNodes).toEqual([])
    })

    it('lists broken models with their error and what they hold up', async () => {
        setFlag(FEATURE_FLAGS.DATA_MODELING_SUSPEND_FAILING_NODES, true)
        await mount('/models')
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess', 'loadEdgesSuccess'])
        await expectLogic(dataWarehouseViewsLogic).toDispatchActions(['loadDataWarehouseSavedQueriesSuccess'])

        // Suspended sorts above failed, because a suspended model has stopped running altogether.
        expect(logic.values.attentionModels.map((row) => [row.node.id, row.problem])).toEqual([
            ['paused', 'Suspended'],
            ['broken', 'Failed'],
        ])

        const paused = logic.values.attentionModels[0]
        expect(paused.reason).toEqual('boom')
        expect(paused.downstreamCount).toEqual(0)

        // The whole cone counts, not just direct children, and the anchor is not one of them.
        const broken = logic.values.attentionModels[1]
        expect(broken.reason).toEqual('Unknown table foo')
        expect(broken.reason).not.toEqual('a stale copy nothing should read')
        expect(broken.downstreamCount).toEqual(2)
        expect(broken.skippedCount).toEqual(2)
    })

    it('lists models behind schedule, minus the ones already listed as broken', async () => {
        await mount('/models')
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess', 'loadEdgesSuccess'])

        // Both blew their cadence, but a broken model is already named above, and saying it
        // twice would send the reader to the same place for two different reasons.
        expect(logic.values.behindSchedule.map((row) => row.node.id)).toEqual(['healthy'])
    })

    it('updates models behind schedule when the scene clock advances without reloading nodes', async () => {
        const initialNow = new Date('2026-01-01T12:00:00Z').getTime()
        const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(initialNow)
        try {
            await mount('/models')
            lineageDataLogic.actions.loadNodesSuccess([
                buildNode('nearly-behind', {
                    sync_interval: '1hour',
                    last_run_at: '2026-01-01T10:01:00Z',
                }),
            ])
            expect(logic.values.behindSchedule).toEqual([])

            nowSpy.mockReturnValue(initialNow + 2 * 60_000)
            logic.actions.setNow(Date.now())

            expect(logic.values.behindSchedule.map((row) => row.node.id)).toEqual(['nearly-behind'])
        } finally {
            nowSpy.mockRestore()
        }
    })
})
