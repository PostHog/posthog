import {
    InternalCaptureEvent,
    InternalCaptureService,
    MAX_EVENTS_PER_CAPTURE_REQUEST,
} from '~/common/services/internal-capture'
import { TeamManager } from '~/common/utils/team-manager'

import { Team } from '../../../types'
import { CyclotronJobInvocationResult, HogFunctionCapturedEvent } from '../../types'
import { CapturedEventsService } from './captured-events.service'

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
            captureBatch: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<InternalCaptureService>

        teamManager = {
            getTeam: jest.fn(),
        } as unknown as jest.Mocked<TeamManager>

        service = new CapturedEventsService(internalCaptureService, teamManager)
    })

    describe('queue + flush', () => {
        it('buffers events and emits them on flush via internalCaptureService', async () => {
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
            expect(internalCaptureService.captureBatch).toHaveBeenNthCalledWith(1, 'token-a', [events[0]])
            expect(internalCaptureService.captureBatch).toHaveBeenNthCalledWith(2, 'token-b', [events[1]])
        })

        it('sends one request per team rather than one per event', async () => {
            service.queue(
                Array.from({ length: 40 }, (_, i) => ({
                    team_token: i % 2 === 0 ? 'token-a' : 'token-b',
                    event: 'click',
                    distinct_id: `u${i}`,
                }))
            )

            await service.flush()

            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(2)
            expect(internalCaptureService.captureBatch.mock.calls.map(([, events]) => events.length)).toEqual([20, 20])
        })

        it('splits a team over several requests once a batch is full', async () => {
            service.queue(
                Array.from({ length: MAX_EVENTS_PER_CAPTURE_REQUEST + 1 }, (_, i) => ({
                    team_token: 'token-a',
                    event: 'click',
                    distinct_id: `u${i}`,
                }))
            )

            await service.flush()

            expect(internalCaptureService.captureBatch.mock.calls.map(([, events]) => events.length)).toEqual([
                MAX_EVENTS_PER_CAPTURE_REQUEST,
                1,
            ])
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

        it('keeps a bounded number of requests in flight', async () => {
            let running = 0
            internalCaptureService.captureBatch.mockImplementation(() => {
                running++
                return new Promise<void>(() => {})
            })
            service.queue(
                Array.from({ length: 50 }, (_, i) => ({
                    team_token: `token-${i}`,
                    event: 'click',
                    distinct_id: 'u1',
                }))
            )

            void service.flush()

            // The controller starts its first wave synchronously, and nothing here ever resolves a request.
            expect(running).toBe(16)
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
                ]),
                buildResult([buildCapturedEvent(1, { event: 'c', distinct_id: 'u3', timestamp: 't3' })]),
            ]

            await service.queueInvocationResults(results)
            await service.flush()

            expect(internalCaptureService.captureBatch).toHaveBeenCalledTimes(2)
            expect(internalCaptureService.captureBatch).toHaveBeenCalledWith('token-team-1', [
                {
                    team_token: 'token-team-1',
                    event: 'a',
                    distinct_id: 'u1',
                    timestamp: 't1',
                    properties: { foo: 'bar' },
                },
                {
                    team_token: 'token-team-1',
                    event: 'c',
                    distinct_id: 'u3',
                    timestamp: 't3',
                    properties: { foo: 'bar' },
                },
            ])
            expect(internalCaptureService.captureBatch).toHaveBeenCalledWith('token-team-2', [
                {
                    team_token: 'token-team-2',
                    event: 'b',
                    distinct_id: 'u2',
                    timestamp: 't2',
                    properties: { foo: 'bar' },
                },
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
