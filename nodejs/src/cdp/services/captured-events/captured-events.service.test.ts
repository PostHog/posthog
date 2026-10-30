import { InternalCaptureEvent, InternalCaptureService } from '~/common/services/internal-capture'
import { TeamManager } from '~/common/utils/team-manager'

import { Team } from '../../../types'
import { CyclotronJobInvocationResult, HogFunctionCapturedEvent } from '../../types'
import {
    CAPTURE_BATCH_CONCURRENCY,
    CAPTURE_BATCH_MAX_BYTES,
    CAPTURE_BATCH_SIZE,
    CAPTURE_QUEUE_MAX_EVENTS,
    CapturedEventsService,
} from './captured-events.service'

const buildTeam = (id: number, apiToken: string): Team =>
    ({
        id,
        api_token: apiToken,
    }) as Team

const buildCapturedEvent = (
    team_id: number,
    overrides: Partial<HogFunctionCapturedEvent> = {}
): HogFunctionCapturedEvent => ({
    team_id,
    event: 'event-name',
    distinct_id: 'distinct-id',
    timestamp: '2025-01-01T00:00:00.000Z',
    properties: { foo: 'bar' },
    ...overrides,
})

const buildResult = (capturedEvents: HogFunctionCapturedEvent[]): CyclotronJobInvocationResult =>
    ({ capturedPostHogEvents: capturedEvents }) as unknown as CyclotronJobInvocationResult

describe('CapturedEventsService', () => {
    let internalCaptureService: jest.Mocked<InternalCaptureService>
    let teamManager: jest.Mocked<TeamManager>
    let service: CapturedEventsService

    beforeEach(() => {
        internalCaptureService = {
            captureBatch: jest.fn().mockResolvedValue({ status: 200 }),
            capture: jest.fn().mockResolvedValue({ status: 200 }),
        } as unknown as jest.Mocked<InternalCaptureService>

        teamManager = {
            getTeam: jest.fn(),
        } as unknown as jest.Mocked<TeamManager>

        service = new CapturedEventsService(internalCaptureService, teamManager)
    })

    describe('queue + flush', () => {
        it('buffers events and sends one batch per team token on flush', async () => {
            const events: InternalCaptureEvent[] = [
                {
                    team_token: 'token-a',
                    event: 'click',
                    distinct_id: 'u1',
                    timestamp: '2025-01-01T00:00:00.000Z',
                    properties: { x: 1 },
                },
                {
                    team_token: 'token-b',
                    event: 'view',
                    distinct_id: 'u2',
                    timestamp: '2025-01-01T00:00:01.000Z',
                    properties: { y: 2 },
                },
            ]

            service.queue(events)
            await service.flush()

            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(2)
            expect(internalCaptureService.captureBatch).toHaveBeenNthCalledWith(1, [events[0]])
            expect(internalCaptureService.captureBatch).toHaveBeenNthCalledWith(2, [events[1]])
        })

        it('splits one token into fixed-size batches and bounds how many are in flight', async () => {
            let inFlight = 0
            let maxInFlight = 0
            internalCaptureService.captureBatch.mockImplementation(async () => {
                inFlight++
                maxInFlight = Math.max(maxInFlight, inFlight)
                await new Promise((resolve) => setImmediate(resolve))
                inFlight--
                return { status: 200 } as any
            })
            const batchCount = CAPTURE_BATCH_CONCURRENCY + 2
            const eventCount = CAPTURE_BATCH_SIZE * (batchCount - 1) + 1
            service.queue(
                Array.from({ length: eventCount }, (_, i) => ({
                    team_token: 'token-a',
                    event: `e${i}`,
                    distinct_id: 'u1',
                }))
            )

            await service.flush()

            const sizes = internalCaptureService.captureBatch.mock.calls.map((call) => call[0].length)
            expect(sizes).toEqual([...Array(batchCount - 1).fill(CAPTURE_BATCH_SIZE), 1])
            expect(maxInFlight).toBe(CAPTURE_BATCH_CONCURRENCY)
        })

        it('keeps the in-flight bound across flushes that overlap', async () => {
            let inFlight = 0
            let maxInFlight = 0
            internalCaptureService.captureBatch.mockImplementation(async () => {
                inFlight++
                maxInFlight = Math.max(maxInFlight, inFlight)
                await new Promise((resolve) => setImmediate(resolve))
                inFlight--
                return { status: 200 } as any
            })
            const queueBatches = (count: number, token: string): void =>
                service.queue(
                    Array.from({ length: CAPTURE_BATCH_SIZE * count }, (_, i) => ({
                        team_token: token,
                        event: `e${i}`,
                        distinct_id: 'u1',
                    }))
                )

            queueBatches(CAPTURE_BATCH_CONCURRENCY, 'token-a')
            const first = service.flush()
            queueBatches(CAPTURE_BATCH_CONCURRENCY, 'token-b')
            const second = service.flush()
            await Promise.all([first, second])

            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(CAPTURE_BATCH_CONCURRENCY * 2)
            expect(maxInFlight).toBe(CAPTURE_BATCH_CONCURRENCY)
        })

        it('starts a new batch before the serialized size passes the byte limit', async () => {
            const big = 'x'.repeat(Math.ceil(CAPTURE_BATCH_MAX_BYTES / 2))
            service.queue(
                Array.from({ length: 3 }, (_, i) => ({
                    team_token: 'token-a',
                    event: `e${i}`,
                    distinct_id: 'u1',
                    properties: { big },
                }))
            )

            await service.flush()

            const sizes = internalCaptureService.captureBatch.mock.calls.map((call) => call[0].length)
            expect(sizes).toEqual([1, 1, 1])
        })

        it('drops an event it cannot serialize and still sends the rest', async () => {
            const circular: Record<string, any> = {}
            circular.self = circular
            service.queue([
                { team_token: 'token-a', event: 'ok', distinct_id: 'u1' },
                { team_token: 'token-a', event: 'loop', distinct_id: 'u1', properties: circular },
            ])

            await service.flush()

            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(1)
            expect(internalCaptureService.captureBatch.mock.calls[0][0].map((e) => e.event)).toEqual(['ok'])
        })

        it('stops queueing past the high-water mark', async () => {
            service.queue(
                Array.from({ length: CAPTURE_QUEUE_MAX_EVENTS + 7 }, (_, i) => ({
                    team_token: 'token-a',
                    event: `e${i}`,
                    distinct_id: 'u1',
                }))
            )

            await service.flush()

            const sent = internalCaptureService.captureBatch.mock.calls.reduce((n, call) => n + call[0].length, 0)
            expect(sent).toBe(CAPTURE_QUEUE_MAX_EVENTS)
        })

        it('bounds single-event retries by the same in-flight limit as batches', async () => {
            internalCaptureService.captureBatch.mockResolvedValue({ status: 400 } as any)
            let inFlight = 0
            let maxInFlight = 0
            internalCaptureService.capture.mockImplementation(async () => {
                inFlight++
                maxInFlight = Math.max(maxInFlight, inFlight)
                await new Promise((resolve) => setImmediate(resolve))
                inFlight--
                return { status: 200 } as any
            })
            service.queue(
                Array.from({ length: CAPTURE_BATCH_CONCURRENCY * 3 }, (_, i) => ({
                    team_token: 'token-a',
                    event: `e${i}`,
                    distinct_id: 'u1',
                }))
            )

            await service.flush()

            expect(internalCaptureService.capture).toHaveBeenCalledTimes(CAPTURE_BATCH_CONCURRENCY * 3)
            expect(maxInFlight).toBe(CAPTURE_BATCH_CONCURRENCY)
        })

        it.each([
            ['a 400 rejection', 400, 2],
            ['a 413 rejection', 413, 2],
            ['a 401 refusal', 401, 0],
            ['a 429 rate limit', 429, 0],
            ['a 5xx failure', 503, 0],
        ])('after %s of a batch, retries its events alone %i times', async (_name, status, singleCaptures) => {
            internalCaptureService.captureBatch.mockResolvedValue({ status } as any)
            service.queue([
                { team_token: 'token-a', event: 'ok', distinct_id: 'u1' },
                { team_token: 'token-a', event: '', distinct_id: 'u1' },
            ])

            await service.flush()

            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(1)
            expect(internalCaptureService.capture).toHaveBeenCalledTimes(singleCaptures)
        })

        it('clears the buffer after flush so a second flush is a no-op', async () => {
            service.queue([
                {
                    team_token: 'token-a',
                    event: 'click',
                    distinct_id: 'u1',
                },
            ])

            await service.flush()
            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(1)

            await service.flush()
            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(1)
        })

        it('queue([]) is a no-op', async () => {
            service.queue([])
            await service.flush()
            expect(internalCaptureService.captureBatch).not.toHaveBeenCalled()
        })

        it('flush with empty buffer does not call internalCaptureService', async () => {
            await service.flush()
            expect(internalCaptureService.captureBatch).not.toHaveBeenCalled()
        })

        it('swallows errors from internalCaptureService.captureBatch', async () => {
            internalCaptureService.captureBatch.mockRejectedValueOnce(new Error('boom'))
            service.queue([
                { team_token: 'token-a', event: 'a', distinct_id: 'u1' },
                { team_token: 'token-b', event: 'b', distinct_id: 'u2' },
            ])

            await expect(service.flush()).resolves.toBeUndefined()
            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(2)
        })
    })

    describe('queueInvocationResults', () => {
        it('extracts capturedPostHogEvents and resolves api_token via teamManager', async () => {
            teamManager.getTeam.mockImplementation((teamId: number) => {
                if (teamId === 1) {
                    return Promise.resolve(buildTeam(1, 'token-team-1'))
                }
                if (teamId === 2) {
                    return Promise.resolve(buildTeam(2, 'token-team-2'))
                }
                return Promise.resolve(null)
            })

            const results: CyclotronJobInvocationResult[] = [
                buildResult([
                    buildCapturedEvent(1, { event: 'a', distinct_id: 'u1', timestamp: 't1' }),
                    buildCapturedEvent(2, { event: 'b', distinct_id: 'u2', timestamp: 't2' }),
                    buildCapturedEvent(1, { event: 'a2', distinct_id: 'u1', timestamp: 't1' }),
                ]),
                buildResult([buildCapturedEvent(1, { event: 'c', distinct_id: 'u3', timestamp: 't3' })]),
            ]

            await service.queueInvocationResults(results)
            await service.flush()

            expect(teamManager.getTeam).toHaveBeenCalledTimes(3)
            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(2)
            // Results resolve concurrently, so the order of events inside a token's batch is not fixed
            const batches = internalCaptureService.captureBatch.mock.calls
                .map((call) => call[0])
                .map((batch) => batch.map((e) => [e.team_token, e.event, e.distinct_id, e.timestamp]).sort())
                .sort((x, y) => x.length - y.length)
            expect(batches).toEqual([
                [['token-team-2', 'b', 'u2', 't2']],
                [
                    ['token-team-1', 'a', 'u1', 't1'],
                    ['token-team-1', 'a2', 'u1', 't1'],
                    ['token-team-1', 'c', 'u3', 't3'],
                ],
            ])
        })

        it('drops events whose team is not found (teamManager returns null)', async () => {
            teamManager.getTeam.mockResolvedValue(null)

            await service.queueInvocationResults([buildResult([buildCapturedEvent(99)])])
            await service.flush()

            expect(internalCaptureService.captureBatch).not.toHaveBeenCalled()
        })

        it('skips results with no captured events', async () => {
            await service.queueInvocationResults([
                { capturedPostHogEvents: [] } as unknown as CyclotronJobInvocationResult,
                { capturedPostHogEvents: undefined } as unknown as CyclotronJobInvocationResult,
            ])
            await service.flush()

            expect(teamManager.getTeam).not.toHaveBeenCalled()
            expect(internalCaptureService.captureBatch).not.toHaveBeenCalled()
        })

        it('handles an empty result array', async () => {
            await service.queueInvocationResults([])
            await service.flush()

            expect(teamManager.getTeam).not.toHaveBeenCalled()
            expect(internalCaptureService.captureBatch).not.toHaveBeenCalled()
        })
    })
})
