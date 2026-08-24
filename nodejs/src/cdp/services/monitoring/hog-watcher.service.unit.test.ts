import { RedisClientPipeline, RedisV2 } from '~/common/redis/redis-v2'

import { createExampleInvocation } from '../../_tests/fixtures'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../../types'
import { createInvocationResult } from '../../utils/invocation-utils'
import {
    HogWatcherConfig,
    HogWatcherService,
    HogWatcherState,
    sameWatcherState,
    sameWatcherStates,
} from './hog-watcher.service'

const WATCHER_CONFIG: HogWatcherConfig = {
    hogCostTimingLowerMs: 50,
    hogCostTimingUpperMs: 550,
    hogCostTiming: 100,
    asyncCostTimingLowerMs: 100,
    asyncCostTimingUpperMs: 5000,
    asyncCostTiming: 20,
    sendEvents: false,
    bucketSize: 10000,
    refillRate: 10,
    ttl: 86400,
    automaticallyDisableFunctions: true,
    thresholdDegraded: 0.8,
    stateLockTtl: 60,
    observeResultsBufferTimeMs: 500,
    observeResultsBufferMaxResults: 500,
}

const createResult = (id: string): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> => {
    const invocation = createExampleInvocation({ id, team_id: 2 })
    invocation.state.timings = [{ kind: 'hog', duration_ms: 100 }]
    return createInvocationResult(invocation, {}, { finished: true })
}

const createClusterRedisStub = (): RedisV2 => ({
    useClient: jest.fn(async (_options, callback) =>
        callback({
            mget: () => Promise.reject(new Error("CROSSSLOT Keys in request don't hash to the same slot")),
        } as any)
    ),
    usePipeline: jest.fn((_options, callback) => {
        const results: [null, unknown][] = []
        const pipeline = {
            get: () => {
                results.push([null, null])
                return pipeline
            },
            checkRateLimitV3: () => {
                results.push([null, [9900, 0]])
                return pipeline
            },
        } as unknown as RedisClientPipeline
        callback(pipeline)
        return Promise.resolve(results)
    }),
})

describe('HogWatcherService unit behavior', () => {
    afterEach(() => {
        jest.useRealTimers()
    })

    it('observes multiple functions without issuing cross-slot commands', async () => {
        const watcher = new HogWatcherService({} as any, WATCHER_CONFIG, createClusterRedisStub())

        await expect(watcher.observeResults([createResult('first'), createResult('second')])).resolves.toBeUndefined()
    })

    it('falls back to the writer when a reader pipeline command fails', async () => {
        const writer = createClusterRedisStub()
        const commandError = new Error('reader command failed')
        const reader: RedisV2 = {
            useClient: jest.fn(),
            usePipeline: jest.fn().mockResolvedValue([[commandError, undefined]]),
        }
        const watcher = new HogWatcherService({} as any, WATCHER_CONFIG, writer, reader)

        await expect(watcher.observeResults([createResult('first'), createResult('second')])).resolves.toBeUndefined()
        expect(writer.usePipeline).toHaveBeenCalledWith(
            expect.objectContaining({ name: 'readStatesForObserve' }),
            expect.any(Function)
        )
    })

    it('rejects buffered callers when a timer-triggered flush fails', async () => {
        jest.useFakeTimers()
        const watcher = new HogWatcherService({} as any, WATCHER_CONFIG, createClusterRedisStub())
        const error = new Error("CROSSSLOT Keys in request don't hash to the same slot")
        jest.spyOn(watcher, 'observeResults').mockRejectedValue(error)

        const bufferedResults = [
            watcher.observeResultsBuffered(createResult('first')),
            watcher.observeResultsBuffered(createResult('second')),
        ]
        const rejections = Promise.all(bufferedResults.map((result) => expect(result).rejects.toBe(error)))
        await jest.advanceTimersByTimeAsync(WATCHER_CONFIG.observeResultsBufferTimeMs)

        await rejections
    })

    // The Redis/Valkey cutover gate is the dualRead mismatch metric on these calls. Comparing
    // `tokens`, which is refilled from the wall clock per read, would saturate it and make the
    // gate useless — so token drift must not read as a mismatch, and a state change must.
    describe('cutover comparators', () => {
        it.each([
            ['token drift alone is equivalent', 10, HogWatcherState.healthy, 9, HogWatcherState.healthy, true],
            ['a differing state is not', 10, HogWatcherState.healthy, 10, HogWatcherState.disabled, false],
        ])('%s', (_name, aTokens, aState, bTokens, bState, expected) => {
            expect(sameWatcherState({ tokens: aTokens, state: aState }, { tokens: bTokens, state: bState })).toBe(
                expected
            )
            expect(
                sameWatcherStates(
                    { fn: { tokens: aTokens, state: aState } },
                    { fn: { tokens: bTokens, state: bState } }
                )
            ).toBe(expected)
        })

        it.each([
            ['a missing id', { a: { tokens: 1, state: HogWatcherState.healthy } }, {}],
            ['an extra id', {}, { a: { tokens: 1, state: HogWatcherState.healthy } }],
        ])('reports %s as a mismatch', (_name, primary, secondary) => {
            expect(sameWatcherStates(primary, secondary)).toBe(false)
        })

        it('treats one side missing entirely as a mismatch', () => {
            expect(sameWatcherState({ tokens: 1, state: HogWatcherState.healthy }, null)).toBe(false)
        })
    })
})
