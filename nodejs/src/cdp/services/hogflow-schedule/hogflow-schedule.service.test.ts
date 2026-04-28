import { HogFlowScheduleService } from './hogflow-schedule.service'

const mockFetch = jest.fn()

jest.mock('~/common/services/internal-fetch', () => ({
    InternalFetchService: jest.fn().mockImplementation(() => ({
        fetch: mockFetch,
    })),
}))

const config = {
    INTERNAL_API_BASE_URL: 'http://localhost:8000',
    INTERNAL_API_SECRET: 'test-secret',
    HOGFLOW_SCHEDULER_POLL_INTERVAL_MS: 60_000,
    HOGFLOW_SCHEDULER_MAX_POLL_INTERVAL_MS: 300_000,
    HOGFLOW_SCHEDULER_HEALTH_TIMEOUT_MS: 600_000,
} as any

function mockDjangoResponse(body: Record<string, unknown>): void {
    mockFetch.mockResolvedValue({
        fetchResponse: {
            status: 200,
            text: () => JSON.stringify(body),
        },
        fetchError: null,
    })
}

describe('HogFlowScheduleService', () => {
    let service: HogFlowScheduleService

    beforeEach(() => {
        jest.clearAllMocks()
        service = new HogFlowScheduleService(config)
        mockDjangoResponse({ processed: [], initialized: [], failed: [] })
        service.start()
        jest.clearAllMocks()
    })

    afterEach(async () => {
        await service.stop()
    })

    describe('pollAndDispatch', () => {
        it('returns true on successful poll with processed schedules', async () => {
            mockDjangoResponse({
                processed: ['schedule-1', 'schedule-2'],
                initialized: [],
                failed: [],
            })

            expect(await service.pollAndDispatch()).toBe(true)
        })

        it('returns true on successful poll with no due schedules', async () => {
            mockDjangoResponse({ processed: [], initialized: [], failed: [] })

            expect(await service.pollAndDispatch()).toBe(true)
        })

        it('returns false when endpoint returns error', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: {
                    status: 500,
                    text: () => 'Internal Server Error',
                },
                fetchError: null,
            })

            expect(await service.pollAndDispatch()).toBe(false)
        })

        it('returns false when fetch fails', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('Connection refused'),
            })

            expect(await service.pollAndDispatch()).toBe(false)
        })
    })

    describe('backoff', () => {
        it('returns false on failure and true on success', async () => {
            mockFetch.mockResolvedValue({ fetchResponse: null, fetchError: new Error('down') })
            expect(await service.pollAndDispatch()).toBe(false)

            mockDjangoResponse({ processed: [], initialized: [], failed: [] })
            expect(await service.pollAndDispatch()).toBe(true)
        })

        it('backs off exponentially capped at 5 minutes', () => {
            const s = service as any
            s.consecutiveFailures = 0
            expect(s.nextSleepMs()).toBe(60_000)

            s.consecutiveFailures = 1
            expect(s.nextSleepMs()).toBe(120_000)

            s.consecutiveFailures = 2
            expect(s.nextSleepMs()).toBe(240_000)

            s.consecutiveFailures = 3
            expect(s.nextSleepMs()).toBe(300_000)

            s.consecutiveFailures = 10
            expect(s.nextSleepMs()).toBe(300_000)
        })
    })

    describe('lifecycle', () => {
        it('does not allow double start', () => {
            mockDjangoResponse({ processed: [], initialized: [], failed: [] })
            const pollPromiseBefore = (service as any).pollPromise
            service.start()
            // Poll promise should be the same instance, not a new one
            expect((service as any).pollPromise).toBe(pollPromiseBefore)
        })
    })

    describe('health check', () => {
        it('reports healthy after successful poll', () => {
            expect(service.isHealthy().status).toBe('ok')
        })

        it('reports unhealthy when last successful poll is too old', () => {
            ;(service as any).lastSuccessfulPollAt = Date.now() - 11 * 60_000
            expect(service.isHealthy().status).toBe('error')
        })

        it('reports unhealthy when not running', async () => {
            await service.stop()
            expect(service.isHealthy().status).toBe('error')
        })
    })
})
