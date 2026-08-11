import { resolveMlAnonymizeMaxConcurrency, resolveMlMirrorRedisConnection } from './config'

describe('ml-mirror config', () => {
    describe('resolveMlAnonymizeMaxConcurrency', () => {
        it.each([
            ['explicit value passes through verbatim, even above the pool', 8, 3, 4, 8],
            ['sentinel resolves to available CPUs when below the pool', 0, 3, 4, 3],
            ['sentinel is capped by the threadpool size', 0, 16, 4, 4],
            ['sentinel never resolves below 1', -1, 0, 0, 1],
        ])('%s', (_name, configured, cpus, poolSize, expected) => {
            expect(resolveMlAnonymizeMaxConcurrency(configured, cpus, poolSize)).toBe(expected)
        })
    })

    describe('resolveMlMirrorRedisConnection', () => {
        const config = (host: string) => ({
            SESSION_RECORDING_ML_REDIS_HOST: host,
            SESSION_RECORDING_ML_REDIS_PORT: 6380,
            SESSION_RECORDING_REDIS_TIMEOUT_MS: 1000,
        })

        it.each([
            ['unset host stays on the shared cluster', ''],
            ['whitespace-only host stays on the shared cluster', '   '],
        ])('%s', (_name, host) => {
            expect(resolveMlMirrorRedisConnection(config(host))).toBeNull()
        })

        it('a configured host moves the lane onto its own instance', () => {
            expect(resolveMlMirrorRedisConnection(config('ml.cache.example'))).toEqual({
                url: 'ml.cache.example',
                options: { port: 6380, commandTimeout: 1000 },
                name: 'session-recording-ml-redis',
            })
        })
    })
})
