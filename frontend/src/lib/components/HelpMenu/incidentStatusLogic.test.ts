import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    RATE_LIMITED_REFRESH_INTERVAL,
    REFRESH_INTERVAL,
    STATUS_PAGE_BASE,
    incidentStatusLogic,
} from './incidentStatusLogic'

describe('incidentStatusLogic', () => {
    let logic: ReturnType<typeof incidentStatusLogic.build>
    let captureException: jest.SpyInstance
    let realFetch: typeof global.fetch

    // Only the status page request is stubbed, so preflight and the other logics keep their mocks.
    function mockStatusPageResponse(status: number): void {
        global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
            String(input).startsWith(STATUS_PAGE_BASE)
                ? Promise.resolve({ ok: status < 400, status, statusText: '' } as Response)
                : realFetch(input, init)
        ) as typeof global.fetch
    }

    beforeEach(() => {
        initKeaTests()
        realFetch = global.fetch
        captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    afterEach(() => {
        logic?.unmount()
        global.fetch = realFetch
        captureException.mockRestore()
    })

    // A status page that answers 5xx or 429 is failing on its own, and nobody can act on the report.
    // Each new upstream status code used to open a new error tracking issue.
    it.each([500, 502, 503, 520, 429])('does not report a %s from the status page', async (status) => {
        mockStatusPageResponse(status)
        logic = incidentStatusLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSummarySuccess'])
        expect(captureException).not.toHaveBeenCalled()
        expect(logic.values.status).toEqual('operational')
    })

    // 403 and 404 mean the status page moved or our access broke, which we can fix.
    it.each([403, 404])('reports a %s from the status page', async (status) => {
        mockStatusPageResponse(status)
        logic = incidentStatusLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSummarySuccess'])
        expect(captureException).toHaveBeenCalledTimes(1)
        // The status stays out of the message so that every code groups into one issue.
        const [error, properties] = captureException.mock.calls[0]
        expect((error as Error).message).toEqual('incident.io summary fetch failed')
        expect(properties).toMatchObject({ status })
    })

    it('polls less often after a 429 than after a healthy response', async () => {
        jest.useFakeTimers()
        try {
            mockStatusPageResponse(429)
            logic = incidentStatusLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSummarySuccess'])
            const callsAfterFirstPoll = (global.fetch as jest.Mock).mock.calls.length

            jest.advanceTimersByTime(REFRESH_INTERVAL)
            expect(global.fetch).toHaveBeenCalledTimes(callsAfterFirstPoll)

            jest.advanceTimersByTime(RATE_LIMITED_REFRESH_INTERVAL - REFRESH_INTERVAL)
            expect(global.fetch).toHaveBeenCalledTimes(callsAfterFirstPoll + 1)
        } finally {
            jest.useRealTimers()
        }
    })
})
