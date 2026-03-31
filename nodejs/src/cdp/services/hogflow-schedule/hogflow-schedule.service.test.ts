import { KafkaProducerWrapper } from '~/kafka/producer'
import { parseJSON } from '~/utils/json-parse'

import { HogFlowScheduleService } from './hogflow-schedule.service'

const mockProduce = jest.fn()
const mockDisconnect = jest.fn()
const mockFetch = jest.fn()

jest.mock('~/kafka/producer', () => ({
    KafkaProducerWrapper: {
        create: jest.fn().mockImplementation(() =>
            Promise.resolve({
                produce: mockProduce,
                disconnect: mockDisconnect,
            })
        ),
    },
}))

jest.mock('~/common/services/internal-fetch', () => ({
    InternalFetchService: jest.fn().mockImplementation(() => ({
        fetch: mockFetch,
    })),
}))

const config = {
    INTERNAL_API_BASE_URL: 'http://localhost:8000',
    INTERNAL_API_SECRET: 'test-secret',
    KAFKA_CLIENT_RACK: undefined,
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

    beforeEach(async () => {
        jest.clearAllMocks()
        service = new HogFlowScheduleService(config)
        // Initialize with empty response so start() completes its first poll
        mockDjangoResponse({ processed: [], initialized: [], failed: [] })
        await service.start()
        jest.clearAllMocks()
    })

    afterEach(async () => {
        await service.stop()
    })

    describe('pollAndDispatch', () => {
        it('produces correct Kafka message for processed schedules', async () => {
            mockDjangoResponse({
                processed: [
                    {
                        schedule_id: 'schedule-1',
                        team_id: 1,
                        hog_flow_id: 'flow-1',
                        filters: { properties: [{ key: 'email', value: '@posthog.com' }] },
                        variables: { greeting: 'Hello' },
                    },
                ],
                initialized: [],
                failed: [],
            })

            await service.pollAndDispatch()

            expect(mockProduce).toHaveBeenCalledWith({
                topic: expect.stringContaining('cdp_batch_hogflow_requests'),
                value: expect.any(Buffer),
                key: '1_flow-1',
            })

            const producedValue = parseJSON(mockProduce.mock.calls[0][0].value.toString())
            expect(producedValue).toEqual({
                teamId: 1,
                hogFlowId: 'flow-1',
                parentRunId: null,
                filters: {
                    properties: [{ key: 'email', value: '@posthog.com' }],
                    filter_test_accounts: false,
                },
                variables: { greeting: 'Hello' },
            })
        })

        it('does not produce to Kafka when no schedules are due', async () => {
            mockDjangoResponse({ processed: [], initialized: [], failed: [] })

            await service.pollAndDispatch()

            expect(mockProduce).not.toHaveBeenCalled()
        })

        it('does not produce to Kafka when endpoint returns error', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: {
                    status: 500,
                    text: () => 'Internal Server Error',
                },
                fetchError: null,
            })

            await service.pollAndDispatch()

            expect(mockProduce).not.toHaveBeenCalled()
        })

        it('does not produce to Kafka when fetch fails', async () => {
            mockFetch.mockResolvedValue({
                fetchResponse: null,
                fetchError: new Error('Connection refused'),
            })

            await service.pollAndDispatch()

            expect(mockProduce).not.toHaveBeenCalled()
        })

        it('dispatches all schedules even when one fails', async () => {
            mockDjangoResponse({
                processed: [
                    { schedule_id: 's1', team_id: 1, hog_flow_id: 'f1', filters: {}, variables: {} },
                    { schedule_id: 's2', team_id: 2, hog_flow_id: 'f2', filters: {}, variables: {} },
                ],
                initialized: [],
                failed: [],
            })

            mockProduce.mockRejectedValueOnce(new Error('Kafka error')).mockResolvedValueOnce(undefined)

            await service.pollAndDispatch()

            expect(mockProduce).toHaveBeenCalledTimes(2)
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
            expect(s.nextSleepMs()).toBe(60_000) // base interval

            s.consecutiveFailures = 1
            expect(s.nextSleepMs()).toBe(120_000) // 60s * 2^1

            s.consecutiveFailures = 2
            expect(s.nextSleepMs()).toBe(240_000) // 60s * 2^2

            s.consecutiveFailures = 3
            expect(s.nextSleepMs()).toBe(300_000) // capped at 5 min

            s.consecutiveFailures = 10
            expect(s.nextSleepMs()).toBe(300_000) // still capped
        })
    })

    describe('lifecycle', () => {
        it('does not allow double start', async () => {
            mockDjangoResponse({ processed: [], initialized: [], failed: [] })

            await service.start()

            // KafkaProducerWrapper.create was called once in beforeEach, not again
            expect(KafkaProducerWrapper.create).not.toHaveBeenCalled()
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
