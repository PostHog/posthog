import { defaultConfig } from '../../../src/config/config'
import { getRedisConnectionOptions } from '../../../src/utils/db/redis'

describe('Redis', () => {
    describe('getRedisConnectionOptions', () => {
        const config = { ...defaultConfig }

        beforeEach(() => {
            config.REDIS_URL = 'redis://localhost:6379'
            config.POSTHOG_REDIS_HOST = 'posthog-redis'
            config.POSTHOG_REDIS_PORT = 6379
            config.POSTHOG_REDIS_PASSWORD = 'posthog-password'
            config.INGESTION_REDIS_HOST = 'ingestion-redis'
            config.INGESTION_REDIS_PORT = 6479
            config.POSTHOG_SESSION_RECORDING_REDIS_HOST = 'session-recording-redis'
            config.POSTHOG_SESSION_RECORDING_REDIS_PORT = 6579
        })

        it('should respond with unique options if all values set', () => {
            expect(getRedisConnectionOptions(config, 'posthog')).toMatchInlineSnapshot(`
                {
                  "options": {
                    "password": "posthog-password",
                    "port": 6379,
                  },
                  "url": "posthog-redis",
                }
            `)
            expect(getRedisConnectionOptions(config, 'ingestion')).toMatchInlineSnapshot(`
                {
                  "options": {
                    "port": 6479,
                  },
                  "url": "ingestion-redis",
                }
            `)
            expect(getRedisConnectionOptions(config, 'session-recording')).toMatchInlineSnapshot(`
                {
                  "options": {
                    "port": 6579,
                  },
                  "url": "session-recording-redis",
                }
            `)
        })

        it('should respond with REDIS_HOST if no options set', () => {
            config.POSTHOG_REDIS_HOST = ''
            config.INGESTION_REDIS_HOST = ''
            config.POSTHOG_SESSION_RECORDING_REDIS_HOST = ''

            expect(getRedisConnectionOptions(config, 'posthog')).toMatchInlineSnapshot(`
                {
                  "url": "redis://localhost:6379",
                }
            `)
            expect(getRedisConnectionOptions(config, 'ingestion')).toMatchInlineSnapshot(`
                {
                  "url": "redis://localhost:6379",
                }
            `)
            expect(getRedisConnectionOptions(config, 'session-recording')).toMatchInlineSnapshot(`
                {
                  "url": "redis://localhost:6379",
                }
            `)
        })

        it('should use the POSTHOG_REDIS_HOST for ingestion if INGESTION_REDIS_HOST is not set', () => {
            config.INGESTION_REDIS_HOST = ''

            expect(getRedisConnectionOptions(config, 'ingestion')).toMatchInlineSnapshot(`
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
})
