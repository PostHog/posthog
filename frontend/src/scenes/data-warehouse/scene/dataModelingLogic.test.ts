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

    // A typo must still find the model, matching the SQL editor sidebar. A revert to String.includes()
    // would drop these hits and make a failed search look like a missing model.
    it('fuzzy-matches the list search so a near-miss term still finds the node', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/': {
                    results: [
                        {
                            id: 'n1',
                            name: 'customer_orders',
                            type: 'view',
                            dag: 'dag-123',
                            created_at: '2024-01-01T00:00:00Z',
                            updated_at: '2024-01-01T00:00:00Z',
                            upstream_count: 0,
                            downstream_count: 0,
                        },
                    ],
                },
            },
        })
        logic = dataModelingLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDataModelingNodesSuccess'])

        logic.actions.setSearchTerm('custmer')
        expect(logic.values.filteredNodes.map((n) => n.name)).toEqual(['customer_orders'])
    })

    it('fuzzy-matches the graph search so a near-miss term still highlights the node', async () => {
        logic = dataModelingLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadDataModelingNodesSuccess', 'loadDataModelingEdgesSuccess'])
            .toFinishAllListeners()

        const nodes: Node[] = [
            {
                id: 'match',
                type: 'model',
                position: { x: 0, y: 0 },
                data: { id: 'match', name: 'customer_orders', type: 'view', upstreamCount: 0, downstreamCount: 0 },
            },
            {
                id: 'other',
                type: 'model',
                position: { x: 100, y: 0 },
                data: { id: 'other', name: 'sessions', type: 'view', upstreamCount: 0, downstreamCount: 0 },
            },
        ]
        logic.actions.setNodesRaw(nodes)
        logic.actions.setDebouncedSearchTerm('custmer')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.searchMatchedNodeIds).toEqual(new Set(['match']))
    })

    // A typo combined with the +/- lineage syntax must still resolve the start node, matching the
    // plain graph search. Reverting the start-node lookup to exact/substring returns an empty set,
    // which blanks the canvas while the list view still finds the model.
    it.each([
        ['+custmer', ['upstream_view', 'customer_orders']],
        ['custmer+', ['customer_orders', 'downstream_view']],
        ['+custmer+', ['upstream_view', 'customer_orders', 'downstream_view']],
    ])('fuzzy-matches a near-miss lineage term (%s) so the graph is not left blank', async (term, expectedIds) => {
        logic = dataModelingLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadDataModelingNodesSuccess', 'loadDataModelingEdgesSuccess'])
            .toFinishAllListeners()

        const nodes: Node[] = [
            {
                id: 'upstream_view',
                type: 'model',
                position: { x: 0, y: 0 },
                data: {
                    id: 'upstream_view',
                    name: 'upstream_view',
                    type: 'view',
                    upstreamCount: 0,
                    downstreamCount: 1,
                },
            },
            {
                id: 'customer_orders',
                type: 'model',
                position: { x: 100, y: 0 },
                data: {
                    id: 'customer_orders',
                    name: 'customer_orders',
                    type: 'view',
                    upstreamCount: 1,
                    downstreamCount: 1,
                },
            },
            {
                id: 'downstream_view',
                type: 'model',
                position: { x: 200, y: 0 },
                data: {
                    id: 'downstream_view',
                    name: 'downstream_view',
                    type: 'view',
                    upstreamCount: 1,
                    downstreamCount: 0,
                },
            },
        ]
        const edges: Edge[] = [
            { id: 'upstream_view->customer_orders', source: 'upstream_view', target: 'customer_orders' },
            { id: 'customer_orders->downstream_view', source: 'customer_orders', target: 'downstream_view' },
        ]

        logic.actions.setNodesRaw(nodes)
        logic.actions.setEdges(edges)
        logic.actions.setDebouncedSearchTerm(term)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.searchMatchedNodeIds).toEqual(new Set(expectedIds))
    })
})
