import { InternalCaptureEvent, InternalCaptureService } from '~/common/services/internal-capture'
import { TeamManager } from '~/common/utils/team-manager'

import { Team } from '../../../types'
import { CyclotronJobInvocationResult, HogFunctionCapturedEvent } from '../../types'
import { CAPTURE_BATCH_CONCURRENCY, CAPTURE_BATCH_SIZE, CapturedEventsService } from './captured-events.service'

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

            // The team is resolved once per team per result, not once per event
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
