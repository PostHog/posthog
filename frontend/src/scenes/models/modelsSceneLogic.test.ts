import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingNode } from '~/types'

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
                    count: 3,
                    results: [
                        buildNode('healthy', { last_run_status: 'Completed' }),
                        buildNode('broken', { last_run_status: 'Failed' }),
                        buildNode('never-ran'),
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
                            suspended: { clickhouse: { at: '2024-01-02T00:00:00Z', reason: 'boom', job_id: 'j1' } },
                        },
                    ],
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['/models', 'models'],
        ['/models?tab=runs', 'runs'],
        ['/models?tab=graph', 'graph'],
        ['/models?tab=nope', 'models'],
    ])('%s opens the %s tab', async (path, tab) => {
        await mount(path)
        expect(logic.values.activeTab).toEqual(tab)
    })

    it('counts models whose last run failed and models that are suspended', async () => {
        await mount('/models')
        await expectLogic(logic).toDispatchActions(['loadNodesSuccess'])
        await expectLogic(dataWarehouseViewsLogic).toDispatchActions(['loadDataWarehouseSavedQueriesSuccess'])

        expect(logic.values.failingNodes.map((node) => node.id)).toEqual(['broken'])
        expect(logic.values.suspendedViews.map((view) => view.id)).toEqual(['query-broken'])
    })
})
