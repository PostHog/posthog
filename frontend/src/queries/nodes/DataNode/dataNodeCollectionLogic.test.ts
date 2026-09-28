import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
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

    const capturedLoads = (): Record<string, any>[] =>
        (posthog.capture as jest.Mock).mock.calls
            .filter(([name, properties]) => name === 'time to see data' && properties.type === 'page_load')
            .map(([, properties]) => properties)

    const mountTile = (id: string): void => {
        logic.actions.mountDataNode(id, {
            id,
            loadData: jest.fn(),
            cancelQuery: jest.fn(),
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

            logic.actions.collectionNodeLoadData('tile-a', 'TrendsQuery')
            logic.actions.collectionNodeLoadData('tile-b', 'TrendsQuery')

            logic.actions.collectionNodeLoadDataSuccess('tile-a', { isCached: true })
            expect(capturedLoads()).toHaveLength(0)

            logic.actions.collectionNodeLoadDataFailure('tile-b')

            expect(capturedLoads()).toEqual([
                expect.objectContaining({
                    context: 'test-collection',
                    action: 'initial_load',
                    status: 'failure',
                    insights_fetched: 2,
                    insights_fetched_cached: 1,
                    failed_tile_count: 1,
                    last_tile_id: 'tile-b',
                    last_tile_kind: 'TrendsQuery',
                    last_tile_status: 'failure',
                    time_to_see_data_ms: expect.any(Number),
                    primary_interaction_id: expect.any(String),
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
            logic.actions.collectionNodeLoadDataSuccess('tile-a')

            expect(capturedLoads().map((p) => p.action)).toEqual(['initial_load', 'refresh', 'update'])
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

        it('counts a tile once when it reloads before the load ends', () => {
            mountTile('tile-a')
            mountTile('tile-b')
            logic.actions.collectionNodeLoadData('tile-a')
            logic.actions.collectionNodeLoadData('tile-b')
            logic.actions.collectionNodeLoadDataFailure('tile-a')

            logic.actions.collectionNodeLoadData('tile-a')
            logic.actions.collectionNodeLoadDataSuccess('tile-b')
            expect(capturedLoads()).toHaveLength(0)

            logic.actions.collectionNodeLoadDataSuccess('tile-a', { isCached: true })

            expect(capturedLoads()).toEqual([
                expect.objectContaining({
                    status: 'success',
                    insights_fetched: 2,
                    insights_fetched_cached: 1,
                    failed_tile_count: 0,
                }),
            ])
        })

        it.each([
            [
                'every loading tile unmounts',
                (): void => {
                    logic.actions.unmountDataNode('tile-a')
                    logic.actions.unmountDataNode('tile-b')
                },
                'navigated_away',
                2,
                undefined,
            ],
            [
                'a loading tile unmounts after its sibling finished',
                (): void => {
                    logic.actions.collectionNodeLoadDataSuccess('tile-b')
                    logic.actions.unmountDataNode('tile-a')
                    logic.actions.unmountDataNode('tile-b')
                },
                'navigated_away',
                1,
                undefined,
            ],
            [
                'a tile unmounts while it reloads',
                (): void => {
                    logic.actions.collectionNodeLoadDataSuccess('tile-a')
                    logic.actions.collectionNodeLoadData('tile-a')
                    logic.actions.collectionNodeLoadDataSuccess('tile-b')
                    logic.actions.unmountDataNode('tile-a')
                },
                'navigated_away',
                1,
                undefined,
            ],
            [
                'the person refreshes',
                (): void => {
                    logic.actions.reloadAll()
                },
                'refreshed',
                2,
                undefined,
            ],
            [
                'the page is hidden',
                (): void => {
                    window.dispatchEvent(new Event('pagehide'))
                },
                'left_app',
                2,
                { transport: 'sendBeacon' },
            ],
        ])('reports one cancelled load when %s', (_, leave, reason, stillLoading, options) => {
            mountTile('tile-a')
            mountTile('tile-b')
            logic.actions.collectionNodeLoadData('tile-a')
            logic.actions.collectionNodeLoadData('tile-b')

            leave()

            expect(posthog.capture).toHaveBeenCalledTimes(1)
            expect(posthog.capture).toHaveBeenCalledWith(
                'time to see data',
                expect.objectContaining({
                    context: 'test-collection',
                    action: 'initial_load',
                    status: 'cancelled',
                    cancel_reason: reason,
                    insights_fetched: 2,
                    tiles_still_loading: stillLoading,
                }),
                options
            )
        })
    })
})
