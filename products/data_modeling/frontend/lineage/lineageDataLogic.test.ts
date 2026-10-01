import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingEdge, DataModelingNode } from '~/types'

import { lineageDataLogic } from './lineageDataLogic'

describe('lineageDataLogic', () => {
    it('loads every page of nodes and edges', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/': ({ request }) => {
                    const page = Number(new URL(request.url).searchParams.get('page') || '1')
                    const nextUrl = new URL(request.url)
                    nextUrl.searchParams.set('page', '2')
                    return [
                        200,
                        {
                            results: [{ id: `node-${page}` } as DataModelingNode],
                            next: page === 1 ? `${nextUrl.pathname}${nextUrl.search}` : null,
                        },
                    ]
                },
                '/api/environments/:team_id/data_modeling_edges/': ({ request }) => {
                    const page = Number(new URL(request.url).searchParams.get('page') || '1')
                    const nextUrl = new URL(request.url)
                    nextUrl.searchParams.set('page', '2')
                    return [
                        200,
                        {
                            results: [{ id: `edge-${page}` } as DataModelingEdge],
                            next: page === 1 ? `${nextUrl.pathname}${nextUrl.search}` : null,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        const logic = lineageDataLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadNodesSuccess', 'loadEdgesSuccess'])

        expect(logic.values.nodes.map((node) => node.id)).toEqual(['node-1', 'node-2'])
        expect(logic.values.edges.map((edge) => edge.id)).toEqual(['edge-1', 'edge-2'])
        logic.unmount()
    })
})
