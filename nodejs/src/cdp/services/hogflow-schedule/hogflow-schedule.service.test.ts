import { IncomingMessage, Server, ServerResponse, createServer } from 'http'
import { AddressInfo } from 'net'

import { HogFlowScheduleService } from './hogflow-schedule.service'

type DjangoAnswer = { status: number; body: string; delayMs?: number }

const answer = (body: Record<string, unknown>, delayMs = 0): DjangoAnswer => ({
    status: 200,
    body: JSON.stringify(body),
    delayMs,
})

const NOTHING_DUE = answer({ processed: [], initialized: [], failed: [] })

describe('HogFlowScheduleService', () => {
    let django: Server
    let djangoUrl: string
    let nextAnswer: DjangoAnswer
    let service: HogFlowScheduleService

    const createService = (overrides: Record<string, number> = {}): HogFlowScheduleService =>
        new HogFlowScheduleService({
            INTERNAL_API_BASE_URL: djangoUrl,
            INTERNAL_API_SECRET: 'test-secret',
            HOGFLOW_SCHEDULER_POLL_INTERVAL_MS: 60_000,
            HOGFLOW_SCHEDULER_MAX_POLL_INTERVAL_MS: 300_000,
            HOGFLOW_SCHEDULER_HEALTH_TIMEOUT_MS: 600_000,
            HOGFLOW_SCHEDULER_REQUEST_TIMEOUT_MS: 10_000,
            ...overrides,
        } as any)

    beforeAll(async () => {
        django = createServer((req: IncomingMessage, res: ServerResponse) => {
            const { status, body, delayMs } = nextAnswer
            const timer = setTimeout(() => res.writeHead(status).end(body), delayMs ?? 0)
            res.on('close', () => clearTimeout(timer))
        })
        await new Promise<void>((resolve) => django.listen(0, '127.0.0.1', resolve))
        djangoUrl = `http://127.0.0.1:${(django.address() as AddressInfo).port}`
    })

    afterAll(async () => {
        django.closeAllConnections()
        await new Promise<void>((resolve) => django.close(() => resolve()))
    })

    beforeEach(async () => {
        nextAnswer = NOTHING_DUE
        service = createService()
        service.start()
        await service.pollAndDispatch()
    })

    afterEach(async () => {
        await service.stop()
    })

    describe('pollAndDispatch', () => {
        it.each([
            [
                'processed schedules',
                answer({ processed: ['schedule-1', 'schedule-2'], initialized: [], failed: [] }),
                true,
            ],
            ['no due schedules', NOTHING_DUE, true],
            ['a Django error', { status: 500, body: 'Internal Server Error' }, false],
        ])('reports whether the poll succeeded for %s', async (_desc, djangoAnswer, succeeded) => {
            nextAnswer = djangoAnswer

            expect(await service.pollAndDispatch()).toBe(succeeded)
        })

        it('reports a failed poll when Django is unreachable', async () => {
            const unreachable = new HogFlowScheduleService({
                ...(service as any).config,
                INTERNAL_API_BASE_URL: 'http://127.0.0.1:1',
            })

            expect(await unreachable.pollAndDispatch()).toBe(false)
        })

        it.each([
            ['succeeds when Django answers within the scheduler request timeout', 1_000, true],
            ['fails when Django answers after the scheduler request timeout', 50, false],
        ])('%s', async (_desc, requestTimeoutMs, succeeded) => {
            const slowPoller = createService({ HOGFLOW_SCHEDULER_REQUEST_TIMEOUT_MS: requestTimeoutMs })
            nextAnswer = answer({ processed: ['schedule-1'], initialized: [], failed: [] }, 300)

            expect(await slowPoller.pollAndDispatch()).toBe(succeeded)
        })
    })

    describe('backoff', () => {
        it('returns false on failure and true on success', async () => {
            nextAnswer = { status: 500, body: 'down' }
            expect(await service.pollAndDispatch()).toBe(false)

            nextAnswer = NOTHING_DUE
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
