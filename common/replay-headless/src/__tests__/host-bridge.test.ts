import type { RecordingSegment } from '@posthog/replay-shared'

import { HostBridge } from '../host-bridge'
import { PLAYER_EMIT_FN, PLAYER_INIT_EVENT } from '../protocol'
import type { PlayerConfig, PlayerMessage } from '../protocol'

const makeSegment = (
    overrides: Partial<RecordingSegment> & Pick<RecordingSegment, 'startTimestamp' | 'endTimestamp'>
): RecordingSegment => ({
    kind: 'window',
    durationMs: overrides.endTimestamp - overrides.startTimestamp,
    isActive: true,
    ...overrides,
})

describe('HostBridge', () => {
    let bridge: HostBridge
    let emitted: PlayerMessage[]

    beforeEach(() => {
        bridge = new HostBridge()
        emitted = []

        // Mock the exposed function callback
        ;(window as any)[PLAYER_EMIT_FN] = (msg: PlayerMessage) => {
            emitted.push(msg)
            return Promise.resolve()
        }
    })

    afterEach(() => {
        delete (window as any)[PLAYER_EMIT_FN]
    })

    describe('signals', () => {
        it('signalStarted emits a started message', () => {
            bridge.signalStarted()
            expect(emitted).toEqual([{ type: 'started' }])
        })

        it('signalEnded emits an ended message', () => {
            bridge.signalEnded()
            expect(emitted).toEqual([{ type: 'ended' }])
        })

        it('setError emits an error message', () => {
            const error = { code: 'TEST', message: 'test error', retryable: false }
            bridge.setError(error)
            expect(emitted).toEqual([{ type: 'error', code: 'TEST', message: 'test error', retryable: false }])
        })

        it('reportLoadingProgress emits a loading_progress message', () => {
            bridge.reportLoadingProgress(2, 10)
            expect(emitted).toEqual([{ type: 'loading_progress', loaded: 2, total: 10 }])
        })
    })

    describe('publishSegments', () => {
        it('emits inactivity periods', () => {
            const segments: RecordingSegment[] = [
                makeSegment({ startTimestamp: 1000000, endTimestamp: 2000000, isActive: true }),
                makeSegment({ startTimestamp: 2000000, endTimestamp: 3000000, isActive: false, kind: 'gap' }),
                makeSegment({ startTimestamp: 3000000, endTimestamp: 5000000, isActive: true }),
            ]

            bridge.publishSegments(segments, 1000000)

            expect(emitted).toEqual([
                {
                    type: 'inactivity_periods',
                    periods: [
                        { ts_from_s: 0, ts_to_s: 1000, active: true },
                        { ts_from_s: 1000, ts_to_s: 2000, active: false },
                        { ts_from_s: 2000, ts_to_s: 4000, active: true },
                    ],
                },
            ])
        })
    })

    describe('waitForConfig', () => {
        it('emits ready and resolves with config when init event fires', async () => {
            const promise = bridge.waitForConfig()

            expect(emitted).toEqual([{ type: 'ready' }])

            const config = { sessionId: 'test', teamId: 1 } as PlayerConfig
            window.dispatchEvent(new CustomEvent(PLAYER_INIT_EVENT, { detail: config }))

            await expect(promise).resolves.toEqual(config)
        })

        it('rejects on timeout', async () => {
            jest.useFakeTimers()
            const promise = bridge.waitForConfig(100)
            jest.advanceTimersByTime(100)
            await expect(promise).rejects.toThrow('posthog-player-init not received within 0.1s')
            jest.useRealTimers()
        })
    })

    describe('waitForStart', () => {
        it('resolves when posthog-player-start event fires', async () => {
            const promise = bridge.waitForStart()
            window.dispatchEvent(new Event('posthog-player-start'))
            await expect(promise).resolves.toBeUndefined()
        })

        it('rejects on timeout', async () => {
            jest.useFakeTimers()
            const promise = bridge.waitForStart(100)
            jest.advanceTimersByTime(100)
            await expect(promise).rejects.toThrow('posthog-player-start not received within 0.1s')
            jest.useRealTimers()
        })
    })
})
