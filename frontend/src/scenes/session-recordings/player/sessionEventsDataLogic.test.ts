import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { RecordingEventType } from '~/types'

import { sessionEventsDataLogic } from './sessionEventsDataLogic'
import { windowIdRegistryLogic } from './windowIdRegistryLogic'

describe('sessionEventsDataLogic', () => {
    let logic: ReturnType<typeof sessionEventsDataLogic.build>

    const base = Date.UTC(2024, 0, 1)

    const makeEvent = (id: string): RecordingEventType => ({
        id,
        event: '$pageview',
        timestamp: '2024-01-01T00:00:00Z',
        elements: [],
        properties: {},
        playerTime: 0,
        fullyLoaded: false,
        distinct_id: 'distinct-id',
    })

    const makeViewportEvent = (
        id: string,
        offsetMs: number,
        windowUuid: string,
        width: number,
        height: number
    ): RecordingEventType => ({
        ...makeEvent(id),
        timestamp: new Date(base + offsetMs).toISOString(),
        properties: {
            $window_id: windowUuid,
            $current_url: 'https://example.com',
            $viewport_width: width,
            $viewport_height: height,
        },
    })

    beforeEach(() => {
        initKeaTests()
        logic = sessionEventsDataLogic({ sessionRecordingId: 'test-session' })
        logic.mount()
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // Regression test: a second loadFullEventData call supersedes the first via kea's
    // breakpoint mechanism, which throws 'kea-listeners breakpoint broke'. Without an
    // isBreakpoint guard, the superseded call's catch block ran anyway and marked its
    // events fullyLoaded, so their properties were never fetched again.
    it('does not mark a superseded loadFullEventData call as fully loaded, nor report it as an error', async () => {
        const eventOne = makeEvent('event-1')
        const eventTwo = makeEvent('event-2')
        logic.actions.loadEventsSuccess([eventOne, eventTwo])

        let resolveFirstQuery: (value: any) => void = () => {}
        const firstQuery = new Promise((resolve) => {
            resolveFirstQuery = resolve
        })
        jest.spyOn(api, 'queryHogQL')
            .mockReturnValueOnce(firstQuery as any)
            .mockResolvedValueOnce({ results: [[JSON.stringify({ some: 'value' }), 'event-2']] } as any)

        logic.actions.loadFullEventData(eventOne)
        logic.actions.loadFullEventData(eventTwo)

        resolveFirstQuery({ results: [[JSON.stringify({ some: 'value' }), 'event-1']] })

        await expectLogic(logic).toDispatchActions(['loadFullEventDataSuccess'])

        expect(posthog.captureException).not.toHaveBeenCalled()
        expect(logic.values.sessionEventsData?.find((e) => e.id === 'event-1')?.fullyLoaded).toBe(false)
        expect(logic.values.sessionEventsData?.find((e) => e.id === 'event-2')?.fullyLoaded).toBe(true)
    })

    // Regression test: a fabricated meta event used to take its viewport from the nearest event
    // in any window, preferring the one after the snapshot. A desktop window would then be sized
    // by a mobile window's event, or by a later resize, rendering responsive UI at the wrong width.
    it('viewportForTimestamp prefers the preceding event within the same window', () => {
        const registry = windowIdRegistryLogic({ sessionRecordingId: 'test-session' })
        registry.mount()
        registry.actions.registerWindowId('win-a') // -> index 1
        registry.actions.registerWindowId('win-b') // -> index 2

        logic.actions.loadEventsSuccess([
            makeViewportEvent('a-wide-before', 100, 'win-a', 1200, 800),
            makeViewportEvent('a-narrow-after', 300, 'win-a', 375, 667),
            makeViewportEvent('b-square', 200, 'win-b', 500, 500),
        ])

        const lookup = logic.values.viewportForTimestamp

        // Window a: the preceding wide viewport wins over the later narrow resize.
        expect(lookup(base + 250, 1)).toEqual({
            width: 1200,
            height: 800,
            href: 'https://example.com',
            source: 'event-window',
        })
        // Window b resolves to its own event, not window a's.
        expect(lookup(base + 250, 2)).toMatchObject({ width: 500, height: 500, source: 'event-window' })
        // A window with no viewport events falls back to the nearest preceding event in any window.
        expect(lookup(base + 250, 3)).toMatchObject({ width: 500, height: 500, source: 'event-fallback' })
        // No windowId also falls back rather than returning nothing.
        expect(lookup(base + 250)).toMatchObject({ source: 'event-fallback' })

        registry.unmount()
    })
})
