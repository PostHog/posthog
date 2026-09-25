import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingEdge, DataModelingNode } from '~/types'

import { lineageDataLogic } from './lineageDataLogic'
import { modelsLineageLogic } from './modelsLineageLogic'

const NODES: DataModelingNode[] = [
    { id: '1', name: 'website_leads', type: 'table' },
    { id: '2', name: 'website_leads_daily', type: 'view' },
    { id: '3', name: 'app_onboarding_leads', type: 'view' },
    { id: '4', name: 'customers', type: 'view' },
] as DataModelingNode[]

// customers feeds website_leads, so an upstream selector keeps a cone of two nodes rather than one.
const EDGES: DataModelingEdge[] = [{ id: 'e1', source_id: '4', target_id: '1' }] as DataModelingEdge[]

describe('modelsLineageLogic', () => {
    let logic: ReturnType<typeof modelsLineageLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/': () => [200, { results: NODES, next: null }],
                '/api/environments/:team_id/data_modeling_edges/': () => [200, { results: EDGES, next: null }],
            },
        })
        initKeaTests()
        logic = modelsLineageLogic()
        logic.mount()
        await expectLogic(lineageDataLogic).toDispatchActions(['loadNodesSuccess', 'loadEdgesSuccess'])
    })

    afterEach(() => {
        logic.unmount()
    })

    // A big DAG has many substring hits for a term; flying to all of them zooms back out to the
    // unreadable overview. Every hit keeps its ring, but the viewport lands on the closest name only.
    it.each([
        ['leads', new Set(['1', '2', '3']), new Set(['1'])],
        ['website_leads', new Set(['1', '2']), new Set(['1'])],
    ])('rings every %p match but focuses the single closest name', async (term, highlighted, focused) => {
        await expectLogic(logic, () => {
            logic.actions.setDebouncedSearchTerm(term)
        }).toMatchValues({
            highlightedNodeIds: highlighted,
            focusNodeIds: focused,
        })
    })

    it('skips a closest match the type filter hid, so the viewport still moves', async () => {
        await expectLogic(logic, () => {
            logic.actions.setTypeFilter(['view'])
            logic.actions.setDebouncedSearchTerm('website_leads')
        }).toMatchValues({
            focusNodeIds: new Set(['2']),
        })
    })

    it('fits the whole surviving cone for a lineage selector instead of one node', async () => {
        await expectLogic(logic, () => {
            logic.actions.setDebouncedSearchTerm('+website_leads')
        }).toMatchValues({
            highlightedNodeIds: new Set(),
            focusNodeIds: new Set(['1', '4']),
        })
    })
})
