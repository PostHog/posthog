import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DataModelingNode } from '~/types'

import { modelsLineageLogic } from './modelsLineageLogic'

function buildNode(name: string): DataModelingNode {
    return {
        id: name,
        name,
        type: 'view',
        dag: 'dag-1',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        upstream_count: 0,
        downstream_count: 0,
    }
}

const NODES = ['orders', 'customers'].map(buildNode)

describe('modelsLineageLogic', () => {
    let logic: ReturnType<typeof modelsLineageLogic.build>
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/data_modeling_nodes/': { count: NODES.length, results: NODES },
                '/api/environments/:team_id/data_modeling_edges/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation()
        logic = modelsLineageLogic()
        logic.mount()
    })

    afterEach(() => {
        captureSpy.mockRestore()
        logic.unmount()
    })

    it('holds back the match count until the graph loads', async () => {
        logic.actions.setDebouncedSearchTerm('orders')

        // The node list starts empty, so counting now would say nothing matched.
        await expectLogic(logic).toMatchValues({ nodesLoading: true, searchMatchCount: null })
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ searchMatchCount: 1 })
    })

    it('counts a match on a misspelled name', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setDebouncedSearchTerm('ordrs')

        await expectLogic(logic).toMatchValues({ searchMatchCount: 1 })
    })

    it('drops a search the user cleared before it settled', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSearchTerm('orders')
        logic.actions.resetFilters()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ debouncedSearchTerm: '' })
        expect(captureSpy).not.toHaveBeenCalled()
    })

    it('reports a settled search with its match count', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSearchTerm('orders')

        await expectLogic(logic).toFinishAllListeners()
        expect(captureSpy).toHaveBeenCalledWith('lineage searched', {
            term_length: 6,
            mode: 'search',
            match_count: 1,
            node_count: 2,
        })
    })
})
