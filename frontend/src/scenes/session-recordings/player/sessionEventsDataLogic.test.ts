import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'
import { RecordingEventType } from '~/types'

import { sessionEventsDataLogic } from './sessionEventsDataLogic'
import { sessionRecordingMetaLogic } from './sessionRecordingMetaLogic'

describe('sessionEventsDataLogic', () => {
    let logic: ReturnType<typeof sessionEventsDataLogic.build>

    const eventRow = (id: string): any[] => [
        id,
        'custom_event',
        '2024-01-01T00:00:10Z',
        '',
        'window-1',
        'https://example.com/path',
        'click',
        800,
        600,
        undefined,
        'distinct-id',
    ]

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

    // The property expansion is best-effort either way: the events are marked loaded and the
    // player keeps working. What differs is reporting. The catch reapplies the gate `initKea`
    // applies to loader failures, so a gateway blip stays out of error tracking while a backend
    // fault still reaches it instead of reading as success.
    it.each<[string, ApiError, number]>([
        ['a transient gateway failure', new ApiError('Service Unavailable', 503), 0],
        ['a backend fault', new ApiError('Internal Server Error', 500), 1],
    ])('degrades gracefully when the loadFullEventData query fails with %s', async (_name, error, reportCalls) => {
        const event = makeEvent('event-1')
        logic.actions.loadEventsSuccess([event])

        jest.spyOn(api, 'queryHogQL').mockRejectedValueOnce(error)

        logic.actions.loadFullEventData(event)

        await expectLogic(logic).toDispatchActions(['loadFullEventDataSuccess'])

        expect(posthog.captureException).toHaveBeenCalledTimes(reportCalls)
        expect(logic.values.sessionEventsData?.find((e) => e.id === 'event-1')?.fullyLoaded).toBe(true)
    })

    it('reports a malformed property payload after the query succeeds', async () => {
        const event = makeEvent('event-1')
        logic.actions.loadEventsSuccess([event])

        jest.spyOn(api, 'queryHogQL').mockResolvedValueOnce({ results: [['not json at all', 'event-1']] } as any)

        logic.actions.loadFullEventData(event)

        await expectLogic(logic).toDispatchActions(['loadFullEventDataFailure'])

        expect(posthog.captureException).toHaveBeenCalledTimes(1)
        expect(logic.values.sessionEventsData?.find((e) => e.id === 'event-1')?.fullyLoaded).toBe(false)
    })

    it('reports a malformed session event after the queries succeed', async () => {
        jest.spyOn(api, 'queryHogQL')
            .mockResolvedValueOnce({ results: [null] } as any)
            .mockResolvedValueOnce({ results: [] } as any)

        sessionRecordingMetaLogic({ sessionRecordingId: 'test-session' }).actions.loadRecordingMetaSuccess({
            id: 'test-session',
            start_time: '2024-01-01T00:00:00Z',
            end_time: '2024-01-01T00:01:00Z',
            person: { uuid: 'person-uuid' },
        } as any)

        await expectLogic(logic).toDispatchActions(['loadEventsFailure'])

        expect(posthog.captureException).toHaveBeenCalledTimes(1)
        expect(logic.values.sessionEventsData).toBeNull()
    })

    // A failed loadEvents degrades to no events, which writes the same value a successful load
    // writes. A second load starts whenever the recording meta loads again, so without a
    // supersede check the older query's late failure empties the list the newer query filled.
    it('does not let a superseded failing loadEvents replace newer events', async () => {
        let rejectFirstQuery: (error: unknown) => void = () => {}
        const firstQuery = new Promise((_, reject) => {
            rejectFirstQuery = reject
        })
        jest.spyOn(api, 'queryHogQL')
            .mockReturnValueOnce(firstQuery as any)
            .mockReturnValueOnce(firstQuery as any)
            .mockResolvedValueOnce({ results: [eventRow('event-1')] } as any)
            .mockResolvedValueOnce({ results: [] } as any)

        // The meta success listener starts the first load, which the explicit dispatch below
        // supersedes while its queries are still in flight.
        sessionRecordingMetaLogic({ sessionRecordingId: 'test-session' }).actions.loadRecordingMetaSuccess({
            id: 'test-session',
            start_time: '2024-01-01T00:00:00Z',
            end_time: '2024-01-01T00:01:00Z',
            person: { uuid: 'person-uuid' },
        } as any)

        logic.actions.loadEvents()
        await expectLogic(logic).toDispatchActions(['loadEventsSuccess'])
        expect(logic.values.sessionEventsData).toHaveLength(1)

        rejectFirstQuery(new ApiError('Service Unavailable', 503))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.sessionEventsData).toHaveLength(1)
        expect(posthog.captureException).not.toHaveBeenCalled()
    })
})
