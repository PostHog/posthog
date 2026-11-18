import { type RedisV2 } from '~/common/redis/redis-v2'

import {
    UNKNOWN_TOKENS_KEY,
    UNKNOWN_TOKENS_MAX_ENTRIES,
    UNKNOWN_TOKEN_CONFIRM_MS,
    UNKNOWN_TOKEN_IDLE_MS,
    UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES,
    UNKNOWN_TOKEN_RETENTION_MS,
    UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS,
    UnknownTokenRecorder,
} from './unknown-token-recorder'

type Call = [string, ...unknown[]]

function setup(opts: { fail?: 'throw' | 'null' | 'command' | 'hang' } = {}) {
    const pipelines: Call[][] = []
    const redis = {
        usePipeline: jest.fn((_options: unknown, cb: (p: Record<string, jest.Mock>) => void) => {
            if (opts.fail === 'throw') {
                return Promise.reject(new Error('redis down'))
            }
            if (opts.fail === 'hang') {
                return new Promise(() => {})
            }
            if (opts.fail === 'null') {
                return Promise.resolve(null)
            }
            const calls: Call[] = []
            const pipeline = new Proxy(
                {},
                {
                    get:
                        (_t, name: string) =>
                        (...args: unknown[]) => {
                            calls.push([name, ...args])
                        },
                }
            ) as Record<string, jest.Mock>
            cb(pipeline)
            pipelines.push(calls)
            return Promise.resolve(calls.map(() => [opts.fail === 'command' ? new Error('boom') : null, 1]))
        }),
    }
    let now = 1_000_000_000_000
    const recorder = new UnknownTokenRecorder(redis as unknown as Pick<RedisV2, 'usePipeline'>, () => now)
    return {
        recorder,
        redis,
        pipelines,
        advance: (ms: number) => {
            now += ms
        },
        now: () => now,
    }
}

const flush = () => new Promise((resolve) => setImmediate(resolve))

describe('UnknownTokenRecorder', () => {
    it('writes a token once it keeps missing past the confirmation window, trimming the set each time', async () => {
        const { recorder, pipelines, advance, now } = setup()
        recorder.record('phc_unknown')
        advance(UNKNOWN_TOKEN_CONFIRM_MS)
        recorder.record('phc_unknown')
        await flush()
        expect(pipelines).toEqual([
            [
                ['zadd', UNKNOWN_TOKENS_KEY, now(), 'phc_unknown'],
                ['expire', UNKNOWN_TOKENS_KEY, 2 * 60 * 60],
                ['zremrangebyscore', UNKNOWN_TOKENS_KEY, '-inf', now() - UNKNOWN_TOKEN_RETENTION_MS],
                ['zremrangebyrank', UNKNOWN_TOKENS_KEY, 0, -(UNKNOWN_TOKENS_MAX_ENTRIES + 1)],
            ],
        ])
    })

    it('never writes a token whose misses all fall inside the confirmation window', async () => {
        const { recorder, redis, advance } = setup()
        recorder.record('phc_new_project')
        advance(UNKNOWN_TOKEN_CONFIRM_MS - 1)
        recorder.record('phc_new_project')
        await flush()
        expect(redis.usePipeline).not.toHaveBeenCalled()
    })

    it('writes a steady stream of misses for one token once per debounce window', async () => {
        const { recorder, redis, advance } = setup()
        recorder.record('phc_unknown')
        advance(UNKNOWN_TOKEN_CONFIRM_MS)
        for (let i = 0; i < 1000; i++) {
            recorder.record('phc_unknown')
        }
        await flush()
        expect(redis.usePipeline).toHaveBeenCalledTimes(1)

        advance(UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS)
        recorder.record('phc_unknown')
        await flush()
        expect(redis.usePipeline).toHaveBeenCalledTimes(2)
    })

    it('writes each distinct token', async () => {
        const { recorder, redis, advance } = setup()
        recorder.record('phc_a')
        recorder.record('phc_b')
        advance(UNKNOWN_TOKEN_CONFIRM_MS)
        recorder.record('phc_a')
        recorder.record('phc_b')
        await flush()
        expect(redis.usePipeline).toHaveBeenCalledTimes(2)
    })

    it('turns away new tokens while full and takes them again once old ones go idle', async () => {
        const { recorder, redis, advance } = setup()
        for (let i = 0; i < UNKNOWN_TOKENS_MAX_ENTRIES; i++) {
            recorder.record(`phc_flood_${i}`)
        }
        recorder.record('phc_late')
        advance(UNKNOWN_TOKEN_CONFIRM_MS)
        recorder.record('phc_late')
        await flush()
        expect(redis.usePipeline).not.toHaveBeenCalled()

        advance(UNKNOWN_TOKEN_IDLE_MS)
        recorder.record('phc_late')
        advance(UNKNOWN_TOKEN_CONFIRM_MS)
        recorder.record('phc_late')
        await flush()
        expect(redis.usePipeline).toHaveBeenCalledTimes(1)
    })

    it('stops starting writes while Redis is not answering', async () => {
        const { recorder, redis, advance } = setup({ fail: 'hang' })
        const tokens = Array.from({ length: UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES + 5 }, (_, i) => `phc_${i}`)
        tokens.forEach((token) => recorder.record(token))
        advance(UNKNOWN_TOKEN_CONFIRM_MS)
        tokens.forEach((token) => recorder.record(token))
        await flush()
        expect(redis.usePipeline).toHaveBeenCalledTimes(UNKNOWN_TOKEN_MAX_IN_FLIGHT_WRITES)
    })

    it.each([
        ['empty', ''],
        ['over-long', 'x'.repeat(201)],
    ])('ignores an %s token', async (_name, token) => {
        const { recorder, redis, advance } = setup()
        recorder.record(token)
        advance(UNKNOWN_TOKEN_CONFIRM_MS)
        recorder.record(token)
        await flush()
        expect(redis.usePipeline).not.toHaveBeenCalled()
    })

    it.each(['throw', 'null', 'command'] as const)('never throws when the write fails (%s)', async (fail) => {
        const { recorder, redis, advance } = setup({ fail })
        recorder.record('phc_unknown')
        advance(UNKNOWN_TOKEN_CONFIRM_MS)
        expect(() => recorder.record('phc_unknown')).not.toThrow()
        await flush()
        expect(redis.usePipeline).toHaveBeenCalledTimes(1)
    })
})
