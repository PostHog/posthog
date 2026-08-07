import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { RecordingEventType } from '~/types'

import { sessionEventsDataLogic } from './sessionEventsDataLogic'

describe('sessionEventsDataLogic', () => {
    let logic: ReturnType<typeof sessionEventsDataLogic.build>

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

    // The property-expansion query can fail transiently (e.g. a 503 from the query gateway).
    // That is already handled gracefully — the events are marked loaded and the player keeps
    // working — so it must not be reported to error tracking, where it fragments into noisy
    // per-environment issues.
    it('degrades gracefully without reporting when loadFullEventData query fails', async () => {
        const event = makeEvent('event-1')
        logic.actions.loadEventsSuccess([event])

        jest.spyOn(api, 'queryHogQL').mockRejectedValueOnce(new Error('Non-OK response (status 503)'))

        logic.actions.loadFullEventData(event)

        await expectLogic(logic).toDispatchActions(['loadFullEventDataSuccess'])

        expect(posthog.captureException).not.toHaveBeenCalled()
        expect(logic.values.sessionEventsData?.find((e) => e.id === 'event-1')?.fullyLoaded).toBe(true)
    })
})
