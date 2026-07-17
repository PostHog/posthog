import { createFeatureFlagCalledDedupRedisConnectionConfig } from './redis-pools'

describe('createFeatureFlagCalledDedupRedisConnectionConfig', () => {
    const base = {
        INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_HOST: '',
        INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_PORT: 6379,
        INGESTION_REDIS_HOST: '',
        INGESTION_REDIS_PORT: 6379,
        POSTHOG_REDIS_HOST: '',
        POSTHOG_REDIS_PORT: 6379,
        POSTHOG_REDIS_PASSWORD: '',
        // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
        REDIS_URL: 'redis://localhost:6379',
    }

    it('uses the dedicated host and port when set', () => {
        expect(
            createFeatureFlagCalledDedupRedisConnectionConfig({
                ...base,
                INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_HOST: 'ff-called-dedup-prod-redis',
                INGESTION_FEATURE_FLAG_CALLED_DEDUP_REDIS_PORT: 6380,
            })
        ).toEqual({ url: 'ff-called-dedup-prod-redis', options: { port: 6380 }, name: 'ff-called-dedup-redis' })
    })

    it('falls back to the ingestion connection (not REDIS_URL) when no host is set', () => {
        expect(
            createFeatureFlagCalledDedupRedisConnectionConfig({
                ...base,
                INGESTION_REDIS_HOST: 'ingestion-prod-redis',
                INGESTION_REDIS_PORT: 6379,
            })
        ).toEqual({ url: 'ingestion-prod-redis', options: { port: 6379 }, name: 'ff-called-dedup-redis' })
    })

    it('falls back to REDIS_URL only when neither dedup nor ingestion hosts are set', () => {
        expect(createFeatureFlagCalledDedupRedisConnectionConfig(base)).toEqual({
            // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
            url: 'redis://localhost:6379',
            name: 'ff-called-dedup-redis',
        })
    })
})
