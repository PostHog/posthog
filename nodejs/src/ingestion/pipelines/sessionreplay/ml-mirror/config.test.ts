import { getMlMirrorConfig, resolveMlMirrorRedisConnection } from './config'

describe('ml-mirror config', () => {
    it.each(['S3_PREFIX', 'PSEUDONYM_SECRET', 'PSEUDONYM_KMS_REGION', 'PSEUDONYM_KEY_FINGERPRINT'] as const)(
        'resolves %s from either environment name with canonical precedence',
        (suffix) => {
            const canonical = `AI_RESEARCH_REPLAY_${suffix}` as const
            const legacy = `SESSION_RECORDING_ML_${suffix}`
            for (const [env, expected] of [
                [{ [legacy]: 'legacy' }, 'legacy'],
                [{ [canonical]: 'canonical' }, 'canonical'],
                [{ [legacy]: 'legacy', [canonical]: 'canonical' }, 'canonical'],
                [{ [legacy]: 'legacy', [canonical]: '' }, ''],
            ] as const) {
                expect(getMlMirrorConfig(env)[canonical]).toBe(expected)
            }
        }
    )

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
