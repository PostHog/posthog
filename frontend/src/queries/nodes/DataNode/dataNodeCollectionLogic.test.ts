import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import {
    DATA_COLLECTION_ABANDONED_EVENT,
    DATA_COLLECTION_LOAD_STARTED_EVENT,
    DATA_COLLECTION_SETTLED_EVENT,
    dataNodeCollectionLogic,
} from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { pageCollectionId } from '~/queries/nodes/DataNode/pageCollections'
import { initKeaTests } from '~/test/init'

jest.mock('posthog-js')

const PAGE_COLLECTION_KEY = pageCollectionId('test-collection')

describe('dataNodeCollectionLogic', () => {
    let logic: ReturnType<typeof dataNodeCollectionLogic.build>

    beforeEach(() => {
        initKeaTests()
        ;(posthog.capture as jest.Mock).mockClear()
        logic = dataNodeCollectionLogic({ key: PAGE_COLLECTION_KEY })
        logic.mount()
    })

    const capturedEvents = (event: string): Record<string, any>[] =>
        (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event).map(([, properties]) => properties)

    const mountTile = (id: string): void => {
        logic.actions.mountDataNode(id, {
            id,
            loadData: jest.fn(),
            cancelQuery: jest.fn(),
            kind: 'TrendsQuery',
        })
    }

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

        // A node starts loading before it registers, so registering must not mark it idle again
        logic.actions.collectionNodeLoadData('tile-c')
        mountTile('tile-c')
        await expectLogic(logic).toMatchValues({ areAnyLoading: true })
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

    describe('load telemetry', () => {
        it('opens one cycle and settles on the last tile, carrying the cycle totals', () => {
            mountTile('tile-a')
            mountTile('tile-b')

            logic.actions.collectionNodeLoadData('tile-a')
            logic.actions.collectionNodeLoadData('tile-b')

            expect(capturedEvents(DATA_COLLECTION_LOAD_STARTED_EVENT)).toEqual([
                expect.objectContaining({
                    collection_key: 'test-collection',
                    trigger: 'initial_load',
                    mounted_tile_count: 2,
                }),
            ])

            logic.actions.collectionNodeLoadDataSuccess('tile-a', { isCached: true })
            expect(capturedEvents(DATA_COLLECTION_SETTLED_EVENT)).toHaveLength(0)

            logic.actions.collectionNodeLoadDataFailure('tile-b')

            expect(capturedEvents(DATA_COLLECTION_SETTLED_EVENT)).toEqual([
                expect.objectContaining({
                    collection_key: 'test-collection',
                    trigger: 'initial_load',
                    tile_count: 2,
                    failed_tile_count: 1,
                    cached_tile_count: 1,
                    unmounted_tile_count: 0,
                    last_tile_id: 'tile-b',
                    last_tile_status: 'failure',
                    duration_ms: expect.any(Number),
                }),
            ])
        })

        it('labels a reloadAll cycle refresh and the cycle after it update', () => {
            logic.actions.mountDataNode('tile-a', {
                id: 'tile-a',
                loadData: jest.fn(() => logic.actions.collectionNodeLoadData('tile-a')),
                cancelQuery: jest.fn(),
            })

            logic.actions.collectionNodeLoadData('tile-a')
            logic.actions.collectionNodeLoadDataSuccess('tile-a')

            logic.actions.reloadAll()
            logic.actions.collectionNodeLoadDataSuccess('tile-a')

            logic.actions.collectionNodeLoadData('tile-a')

            expect(capturedEvents(DATA_COLLECTION_LOAD_STARTED_EVENT).map((p) => p.trigger)).toEqual([
                'initial_load',
                'refresh',
                'update',
            ])
        })

        it('stays silent for a collection not registered as a page container', () => {
            const privateLogic = dataNodeCollectionLogic({ key: 'a-trace-or-chart-id' })
            privateLogic.mount()
            privateLogic.actions.mountDataNode('tile-a', { id: 'tile-a', loadData: jest.fn(), cancelQuery: jest.fn() })

            privateLogic.actions.collectionNodeLoadData('tile-a')
            privateLogic.actions.collectionNodeLoadDataSuccess('tile-a')

            expect(posthog.capture).not.toHaveBeenCalled()
            privateLogic.unmount()
        })

        it('reports abandoned, not settled, when every loading tile unmounts', () => {
            mountTile('tile-a')
            mountTile('tile-b')
            logic.actions.collectionNodeLoadData('tile-a')
            logic.actions.collectionNodeLoadData('tile-b')

            logic.actions.unmountDataNode('tile-a')
            expect(capturedEvents(DATA_COLLECTION_ABANDONED_EVENT)).toHaveLength(0)

            logic.actions.unmountDataNode('tile-b')

            expect(capturedEvents(DATA_COLLECTION_ABANDONED_EVENT)).toEqual([
                expect.objectContaining({
                    collection_key: 'test-collection',
                    trigger: 'initial_load',
                    tile_count: 2,
                    tiles_still_loading: 2,
                    duration_ms: expect.any(Number),
                }),
            ])
            expect(capturedEvents(DATA_COLLECTION_SETTLED_EVENT)).toHaveLength(0)
        })

        it('settles when a tile unmounts mid-load and the rest have finished', () => {
            mountTile('tile-a')
            mountTile('tile-b')
            logic.actions.collectionNodeLoadData('tile-a')
            logic.actions.collectionNodeLoadData('tile-b')
            logic.actions.collectionNodeLoadDataSuccess('tile-b')

            logic.actions.unmountDataNode('tile-a')

            expect(capturedEvents(DATA_COLLECTION_SETTLED_EVENT)).toEqual([
                expect.objectContaining({
                    tile_count: 2,
                    unmounted_tile_count: 1,
                    last_tile_id: 'tile-a',
                    last_tile_status: 'unmounted',
                }),
            ])
            expect(capturedEvents(DATA_COLLECTION_ABANDONED_EVENT)).toHaveLength(0)
        })
    })
})
