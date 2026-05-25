import { expectLogic } from 'kea-test-utils'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { initKeaTests } from '~/test/init'

describe('dataNodeCollectionLogic', () => {
    let logic: ReturnType<typeof dataNodeCollectionLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = dataNodeCollectionLogic({ key: 'test-collection' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('reloadAll fires loadData on every mounted data node with force_async', () => {
        const loadDataA = jest.fn()
        const loadDataB = jest.fn()
        const loadDataC = jest.fn()
        const cancelQuery = jest.fn()

        logic.actions.mountDataNode('tile-a', { id: 'tile-a', loadData: loadDataA, cancelQuery })
        logic.actions.mountDataNode('tile-b', { id: 'tile-b', loadData: loadDataB, cancelQuery })
        logic.actions.mountDataNode('tile-c', { id: 'tile-c', loadData: loadDataC, cancelQuery })

        logic.actions.reloadAll()

        expect(loadDataA).toHaveBeenCalledTimes(1)
        expect(loadDataA).toHaveBeenCalledWith('force_async')
        expect(loadDataB).toHaveBeenCalledTimes(1)
        expect(loadDataB).toHaveBeenCalledWith('force_async')
        expect(loadDataC).toHaveBeenCalledTimes(1)
        expect(loadDataC).toHaveBeenCalledWith('force_async')
    })

    it('mountDataNode dedupes by id, replacing the prior loadData reference', () => {
        const stale = jest.fn()
        const fresh = jest.fn()
        const cancelQuery = jest.fn()

        logic.actions.mountDataNode('tile-a', { id: 'tile-a', loadData: stale, cancelQuery })
        logic.actions.mountDataNode('tile-a', { id: 'tile-a', loadData: fresh, cancelQuery })

        logic.actions.reloadAll()

        expect(stale).not.toHaveBeenCalled()
        expect(fresh).toHaveBeenCalledWith('force_async')
    })

    it('unmountDataNode removes the node so reloadAll skips it', () => {
        const loadDataA = jest.fn()
        const loadDataB = jest.fn()
        const cancelQuery = jest.fn()

        logic.actions.mountDataNode('tile-a', { id: 'tile-a', loadData: loadDataA, cancelQuery })
        logic.actions.mountDataNode('tile-b', { id: 'tile-b', loadData: loadDataB, cancelQuery })
        logic.actions.unmountDataNode('tile-a')

        logic.actions.reloadAll()

        expect(loadDataA).not.toHaveBeenCalled()
        expect(loadDataB).toHaveBeenCalledWith('force_async')
    })

    it('areAnyLoading reflects per-node load state', async () => {
        const cancelQuery = jest.fn()
        logic.actions.mountDataNode('tile-a', { id: 'tile-a', loadData: jest.fn(), cancelQuery })
        logic.actions.mountDataNode('tile-b', { id: 'tile-b', loadData: jest.fn(), cancelQuery })

        await expectLogic(logic).toMatchValues({ areAnyLoading: false })

        logic.actions.collectionNodeLoadData('tile-a')
        await expectLogic(logic).toMatchValues({ areAnyLoading: true })

        logic.actions.collectionNodeLoadDataSuccess('tile-a')
        await expectLogic(logic).toMatchValues({ areAnyLoading: false })
    })

    it('cancelAllLoading only cancels nodes whose status is loading', () => {
        const cancelA = jest.fn()
        const cancelB = jest.fn()
        logic.actions.mountDataNode('tile-a', { id: 'tile-a', loadData: jest.fn(), cancelQuery: cancelA })
        logic.actions.mountDataNode('tile-b', { id: 'tile-b', loadData: jest.fn(), cancelQuery: cancelB })

        logic.actions.collectionNodeLoadData('tile-a')
        // tile-b never started loading
        logic.actions.cancelAllLoading()

        expect(cancelA).toHaveBeenCalledTimes(1)
        expect(cancelB).not.toHaveBeenCalled()
    })
})
