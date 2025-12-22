import { defaultConfig } from '../../../src/config/config'
import {
    getIngestionRedisConnectionOptions,
    getPosthogRedisConnectionOptions,
    getSessionRecordingRedisConnectionOptions,
} from '../../../src/utils/db/redis'

describe('Redis', () => {
    describe('getPosthogRedisConnectionOptions', () => {
        const config = { ...defaultConfig }

        beforeEach(() => {
            config.REDIS_URL = 'redis://localhost:6379'
            config.POSTHOG_REDIS_HOST = 'posthog-redis'
            config.POSTHOG_REDIS_PORT = 6379
            config.POSTHOG_REDIS_PASSWORD = 'posthog-password'
        })

        it('should respond with posthog options if set', () => {
            expect(getPosthogRedisConnectionOptions(config)).toMatchInlineSnapshot(`
                {
                  "options": {
                    "password": "posthog-password",
                    "port": 6379,
                  },
                  "url": "posthog-redis",
                }
            `)
        })

        it('should respond with REDIS_URL if no options set', () => {
            config.POSTHOG_REDIS_HOST = ''

            expect(getPosthogRedisConnectionOptions(config)).toMatchInlineSnapshot(`
                {
                  "url": "redis://localhost:6379",
                }
            `)
        })
    })

    describe('getIngestionRedisConnectionOptions', () => {
        const config = { ...defaultConfig }

        beforeEach(() => {
            config.REDIS_URL = 'redis://localhost:6379'
            config.POSTHOG_REDIS_HOST = 'posthog-redis'
            config.POSTHOG_REDIS_PORT = 6379
            config.POSTHOG_REDIS_PASSWORD = 'posthog-password'
            config.INGESTION_REDIS_HOST = 'ingestion-redis'
            config.INGESTION_REDIS_PORT = 6479
        })

        it('should respond with ingestion options if set', () => {
            expect(getIngestionRedisConnectionOptions(config)).toMatchInlineSnapshot(`
                {
                  "options": {
                    "port": 6479,
                  },
                  "url": "ingestion-redis",
                }
            `)
        })

        it('should use the POSTHOG_REDIS_HOST for ingestion if INGESTION_REDIS_HOST is not set', () => {
            config.INGESTION_REDIS_HOST = ''

            expect(getIngestionRedisConnectionOptions(config)).toMatchInlineSnapshot(`
                {
                  "options": {
                    "password": "posthog-password",
                    "port": 6379,
                  },
                  "url": "posthog-redis",
                }
            `)
        })
    })

    describe('getSessionRecordingRedisConnectionOptions', () => {
        const config = { ...defaultConfig }

        beforeEach(() => {
            config.REDIS_URL = 'redis://localhost:6379'
            config.POSTHOG_SESSION_RECORDING_REDIS_HOST = 'session-recording-redis'
            config.POSTHOG_SESSION_RECORDING_REDIS_PORT = 6579
        })

        it('should respond with session recording options if set', () => {
            expect(getSessionRecordingRedisConnectionOptions(config)).toMatchInlineSnapshot(`
                {
                  "options": {
                    "port": 6579,
                  },
                  "url": "session-recording-redis",
                }
            `)
        })

        it('should respond with REDIS_URL if no options set', () => {
            config.POSTHOG_SESSION_RECORDING_REDIS_HOST = ''

            expect(getSessionRecordingRedisConnectionOptions(config)).toMatchInlineSnapshot(`
                {
                  "url": "redis://localhost:6379",
                }
            `)
        })
    })
})
