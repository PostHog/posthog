import { type RedisV2 } from '~/common/redis/redis-v2'

import {
    UNKNOWN_TOKENS_KEY,
    UNKNOWN_TOKENS_MAX_ENTRIES,
    UNKNOWN_TOKEN_RETENTION_MS,
    UNKNOWN_TOKEN_WRITE_DEBOUNCE_MS,
    UnknownTokenRecorder,
} from './unknown-token-recorder'

type Call = [string, ...unknown[]]

function setup(opts: { fail?: 'throw' | 'null' | 'command' } = {}) {
    const pipelines: Call[][] = []
    const redis = {
        usePipeline: jest.fn((_options: unknown, cb: (p: Record<string, jest.Mock>) => void) => {
            if (opts.fail === 'throw') {
                return Promise.reject(new Error('redis down'))
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
    it('adds the token to the sorted set scored by now', async () => {
        const { recorder, pipelines, now } = setup()
        recorder.record('phc_unknown')
        await flush()
        expect(pipelines).toHaveLength(1)
        expect(pipelines[0]).toContainEqual(['zadd', UNKNOWN_TOKENS_KEY, now(), 'phc_unknown'])
    })

    it('writes a steady stream of misses for one token once per debounce window', async () => {
        const { recorder, redis, advance } = setup()
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
        const { recorder, redis } = setup()
        recorder.record('phc_a')
        recorder.record('phc_b')
        await flush()
        expect(redis.usePipeline).toHaveBeenCalledTimes(2)
    })

    it('trims old and excess entries on the first write and then only now and then', async () => {
        const { recorder, pipelines, advance, now } = setup()
        recorder.record('phc_a')
        await flush()
        expect(pipelines[0]).toContainEqual([
            'zremrangebyscore',
            UNKNOWN_TOKENS_KEY,
            '-inf',
            now() - UNKNOWN_TOKEN_RETENTION_MS,
        ])
        expect(pipelines[0]).toContainEqual([
            'zremrangebyrank',
            UNKNOWN_TOKENS_KEY,
            0,
            -(UNKNOWN_TOKENS_MAX_ENTRIES + 1),
        ])

        advance(1000)
        recorder.record('phc_b')
        await flush()
        expect(pipelines[1].map(([name]) => name)).not.toContain('zremrangebyscore')

        advance(10 * 60 * 1000)
        recorder.record('phc_c')
        await flush()
        expect(pipelines[2].map(([name]) => name)).toContain('zremrangebyscore')
    })

    it.each([
        ['empty', ''],
        ['over-long', 'x'.repeat(201)],
    ])('ignores an %s token', async (_name, token) => {
        const { recorder, redis } = setup()
        recorder.record(token)
        await flush()
        expect(redis.usePipeline).not.toHaveBeenCalled()
    })

    it.each(['throw', 'null', 'command'] as const)('never throws when the write fails (%s)', async (fail) => {
        const { recorder, redis } = setup({ fail })
        expect(() => recorder.record('phc_unknown')).not.toThrow()
        await flush()
        expect(redis.usePipeline).toHaveBeenCalledTimes(1)
    })
})
