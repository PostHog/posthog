import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { initKeaTests } from '~/test/init'

import { WEB_ANALYTICS_DATA_COLLECTION_NODE_ID } from './common'
import { webAnalyticsLoadTimeLogic } from './webAnalyticsLoadTimeLogic'

jest.mock('posthog-js')

describe('webAnalyticsLoadTimeLogic', () => {
    let logic: ReturnType<typeof webAnalyticsLoadTimeLogic.build>
    let collection: ReturnType<typeof dataNodeCollectionLogic.build>

    beforeEach(() => {
        initKeaTests()
        collection = dataNodeCollectionLogic({ key: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID })
        collection.mount()
        ;(posthog.capture as jest.Mock).mockClear()
        logic = webAnalyticsLoadTimeLogic()
        logic.mount()
    })

    afterEach(() => {
        if (logic.isMounted()) {
            logic.unmount()
        }
        collection.unmount()
    })

    const abandonedCalls = (): any[][] =>
        (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'web_analytics_dashboard_load_abandoned'
        )

    it('captures dashboard_mounted on mount', () => {
        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_dashboard_mounted',
            expect.objectContaining({ tile_skeletons_enabled: expect.any(Boolean) })
        )
    })

    it('captures dashboard_loaded once after first loading→idle transition', async () => {
        await expectLogic(logic, () => {
            collection.actions.collectionNodeLoadData('a')
        }).toMatchValues({ areAnyLoading: true })

        await expectLogic(logic, () => {
            collection.actions.collectionNodeLoadDataSuccess('a')
        }).toMatchValues({ areAnyLoading: false })

        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_dashboard_loaded',
            expect.objectContaining({ duration_ms: expect.any(Number), tile_skeletons_enabled: expect.any(Boolean) })
        )

        const loadedCallsBefore = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'web_analytics_dashboard_loaded'
        ).length

        collection.actions.collectionNodeLoadData('b')
        collection.actions.collectionNodeLoadDataSuccess('b')

        const loadedCallsAfter = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'web_analytics_dashboard_loaded'
        ).length
        expect(loadedCallsAfter).toBe(loadedCallsBefore)
    })

    it('captures dashboard_loaded on the last finishing node, not the first', async () => {
        collection.actions.collectionNodeLoadData('a')
        collection.actions.collectionNodeLoadData('b')

        const captureCount = (): number =>
            (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === 'web_analytics_dashboard_loaded')
                .length

        collection.actions.collectionNodeLoadDataSuccess('a')
        expect(captureCount()).toBe(0)

        await expectLogic(logic, () => {
            collection.actions.collectionNodeLoadDataSuccess('b')
        }).toMatchValues({ areAnyLoading: false })
        expect(captureCount()).toBe(1)
    })

    it('also captures dashboard_loaded when the last node fails', async () => {
        collection.actions.collectionNodeLoadData('a')

        await expectLogic(logic, () => {
            collection.actions.collectionNodeLoadDataFailure('a')
        }).toMatchValues({ areAnyLoading: false })

        expect(posthog.capture).toHaveBeenCalledWith(
            'web_analytics_dashboard_loaded',
            expect.objectContaining({ duration_ms: expect.any(Number) })
        )
    })

    it('does not capture dashboard_loaded if no loading was ever observed', () => {
        const loadedCalls = (posthog.capture as jest.Mock).mock.calls.filter(
            ([event]) => event === 'web_analytics_dashboard_loaded'
        )
        expect(loadedCalls).toHaveLength(0)
    })

    it.each([
        { name: 'before any query starts', startQuery: false },
        { name: 'while queries are loading', startQuery: true },
    ])('captures load_abandoned when navigating away $name', ({ startQuery }) => {
        if (startQuery) {
            collection.actions.collectionNodeLoadData('a')
        }
        logic.unmount()

        expect(abandonedCalls()).toEqual([
            [
                'web_analytics_dashboard_load_abandoned',
                expect.objectContaining({
                    duration_ms: expect.any(Number),
                    reason: 'navigated_away',
                    queries_started: startQuery,
                }),
                undefined,
            ],
        ])
    })

    it('captures load_abandoned once via sendBeacon when the page is hidden mid-load', () => {
        collection.actions.collectionNodeLoadData('a')
        window.dispatchEvent(new Event('pagehide'))
        logic.unmount()

        expect(abandonedCalls()).toEqual([
            [
                'web_analytics_dashboard_load_abandoned',
                expect.objectContaining({ reason: 'left_app', queries_started: true }),
                { transport: 'sendBeacon' },
            ],
        ])
    })

    it('does not capture load_abandoned after dashboard_loaded', () => {
        collection.actions.collectionNodeLoadData('a')
        collection.actions.collectionNodeLoadDataSuccess('a')
        logic.unmount()

        expect(abandonedCalls()).toHaveLength(0)
    })
})
