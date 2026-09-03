import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dataModelingLogic } from './dataModelingLogic'
import type { Edge, Node } from './modeling/types'

describe('dataModelingLogic', () => {
    let logic: ReturnType<typeof dataModelingLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_dags/': {
                    results: [
                        {
                            id: 'dag-123',
                            name: 'Test DAG',
                            description: '',
                            sync_frequency: '24hour',
                            node_count: 0,
                            created_at: '2024-01-01T00:00:00Z',
                            updated_at: '2024-01-01T00:00:00Z',
                        },
                    ],
                },
                '/api/environments/:team_id/data_modeling_nodes/': { results: [] },
                '/api/environments/:team_id/data_modeling_edges/': { results: [] },
                '/api/environments/:team_id/data_modeling_jobs/recent/': [],
                '/api/environments/:team_id/data_modeling_jobs/running/': [],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The Models scene's DagsTab links here with ?dag=<id> to open a specific DAG's graph — a
    // regression here would silently send that link to the wrong (or persisted) DAG instead.
    it('selects the DAG from a ?dag= URL param and filters node/edge loads by it', async () => {
        const nodesSpy = jest.spyOn(api.dataModelingNodes, 'list')
        const edgesSpy = jest.spyOn(api.dataModelingEdges, 'list')

        router.actions.push(urls.dataOps('modeling', 'dag-123'))
        logic = dataModelingLogic()
        logic.mount()

        expect(logic.values.selectedDagId).toBe('dag-123')
        await expectLogic(logic).toDispatchActions(['loadDataModelingNodesSuccess', 'loadDataModelingEdgesSuccess'])

        expect(nodesSpy).toHaveBeenCalledWith('dag-123')
        expect(edgesSpy).toHaveBeenCalledWith('dag-123')
    })

    it('keeps the persisted DAG selection when the URL has no ?dag= param', () => {
        router.actions.push(urls.dataOps('modeling', 'dag-123'))
        logic = dataModelingLogic()
        logic.mount()
        expect(logic.values.selectedDagId).toBe('dag-123')
        logic.unmount()

        router.actions.push(urls.dataOps('modeling'))
        logic = dataModelingLogic()
        logic.mount()

        expect(logic.values.selectedDagId).toBe('dag-123')
    })

    it('lays out only the nodes matched by a lineage search', async () => {
        logic = dataModelingLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadDataModelingNodesSuccess', 'loadDataModelingEdgesSuccess'])
            .toFinishAllListeners()

        const nodes: Node[] = [
            {
                id: 'source',
                type: 'model',
                position: { x: 0, y: 0 },
                data: {
                    id: 'source',
                    name: 'this_view',
                    type: 'view',
                    upstreamCount: 0,
                    downstreamCount: 1,
                },
            },
            {
                id: 'unrelated',
                type: 'model',
                position: { x: 5000, y: 0 },
                data: {
                    id: 'unrelated',
                    name: 'unrelated_view',
                    type: 'view',
                    upstreamCount: 0,
                    downstreamCount: 0,
                },
            },
            {
                id: 'target',
                type: 'model',
                position: { x: 10000, y: 0 },
                data: {
                    id: 'target',
                    name: 'dependent_view',
                    type: 'view',
                    upstreamCount: 1,
                    downstreamCount: 0,
                },
            },
        ]
        const edges: Edge[] = [
            {
                id: 'source->target',
                source: 'source',
                target: 'target',
            },
        ]

        logic.actions.setNodesRaw(nodes)
        logic.actions.setEdges(edges)
        logic.actions.setDebouncedSearchTerm('this_view+')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.enrichedNodes.map((node) => node.id)).toEqual(['source', 'target'])
        const [source, target] = logic.values.enrichedNodes
        expect(Math.abs(target.position.x - source.position.x)).toBeLessThan(1000)
    })
})
