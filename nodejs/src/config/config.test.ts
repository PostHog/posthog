import { buildIntegerMatcher, buildStringMatcher, getDefaultConfig, getDefaultConfigWithEnv } from './config'
import { defineConfig, mergeConfigs } from './define-config'

describe('defineConfig', () => {
    test('defaults evaluates factory functions', () => {
        const section = defineConfig({
            TEST_HOST: () => 'localhost',
            TEST_PORT: () => 8080,
            TEST_ENABLED: () => true,
        })

        expect(section.defaults()).toEqual({
            TEST_HOST: 'localhost',
            TEST_PORT: 8080,
            TEST_ENABLED: true,
        })
    })

    test('defaults calls factories lazily on each invocation', () => {
        let counter = 0
        const section = defineConfig({
            TEST_VALUE: () => ++counter,
        })

        expect(section.defaults().TEST_VALUE).toBe(1)
        expect(section.defaults().TEST_VALUE).toBe(2)
    })

    test('nullable types preserve null and undefined defaults', () => {
        const section = defineConfig({
            TEST_NULLABLE: (): string | null => null,
            TEST_OPTIONAL: (): string | undefined => undefined,
        })
        const defaults = section.defaults()

        expect(defaults.TEST_NULLABLE).toBeNull()
        expect(defaults.TEST_OPTIONAL).toBeUndefined()
    })

    test('mergeConfigs detects duplicate keys', () => {
        const a = defineConfig({ TEST_DUPE: () => 1 })
        const b = defineConfig({ TEST_DUPE: () => 2 })

        expect(() => mergeConfigs(a, b)).toThrow('Config key "TEST_DUPE" is defined in multiple config sections')
    })

    test('overrideWithEnv works with defineConfig-produced defaults', () => {
        const env = {
            SESSION_RECORDING_API_REDIS_HOST: 'redis.prod',
            SESSION_RECORDING_API_REDIS_PORT: '6380',
        }
        const overridden = getDefaultConfigWithEnv(env)

        expect(overridden.SESSION_RECORDING_API_REDIS_HOST).toBe('redis.prod')
        expect(overridden.SESSION_RECORDING_API_REDIS_PORT).toBe(6380)
    })

    test('all config sections are included in getDefaultConfig', () => {
        const config = getDefaultConfig()

        // Session recording
        expect(config.SESSION_RECORDING_API_REDIS_HOST).toBe('127.0.0.1')
        expect(config.SESSION_RECORDING_LOCAL_DIRECTORY).toBe('.tmp/sessions')
        // Common
        expect(config.REDIS_URL).toBe('redis://127.0.0.1')
        // CDP
        expect(config.CDP_WATCHER_BUCKET_SIZE).toBe(10000)
        // Ingestion
        expect(config.INGESTION_CONCURRENCY).toBe(10)
        // Logs ingestion
        expect(config.LOGS_INGESTION_CONSUMER_GROUP_ID).toBe('ingestion-logs')
    })
})

describe('config', () => {
    test('overrideWithEnv 1', () => {
        const defaultConfig = getDefaultConfig()
        const env = {
            INSTRUMENT_THREAD_PERFORMANCE: 'false',
            TASK_TIMEOUT: '3008',
            REDIS_URL: '0.0.0.0',
            BASE_DIR: undefined,
        }
        const config = getDefaultConfigWithEnv(env)

        expect(config.INSTRUMENT_THREAD_PERFORMANCE).toEqual(false)
        expect(config.TASK_TIMEOUT).toEqual(3008)
        expect(config.REDIS_URL).toEqual('0.0.0.0')
        expect(config.BASE_DIR).toEqual(defaultConfig.BASE_DIR)
    })

    test('overrideWithEnv 2', () => {
        const env = {
            INSTRUMENT_THREAD_PERFORMANCE: '1',
            TASK_TIMEOUT: '3008.12',
        }
        const config = getDefaultConfigWithEnv(env)

        expect(config.INSTRUMENT_THREAD_PERFORMANCE).toEqual(true)
        expect(config.TASK_TIMEOUT).toEqual(3008.12)
    })

    describe('DATABASE_URL', () => {
        test('Error if DATABASE_URL is not set AND POSTHOG_DB_NAME is not set', () => {
            const env = {
                DATABASE_URL: '',
                POSTHOG_DB_NAME: '',
            }
            expect(() => getDefaultConfigWithEnv(env)).toThrow(
                'You must specify either DATABASE_URL or the database options POSTHOG_DB_NAME, POSTHOG_DB_USER, POSTHOG_DB_PASSWORD, POSTHOG_POSTGRES_HOST, POSTHOG_POSTGRES_PORT!'
            )
        })

        test('Set DATABASE_URL to a string composed of URL-encoded connection options if DATABASE_URL is not explictly set', () => {
            const env = {
                DATABASE_URL: '',
                POSTHOG_DB_NAME: 'mydb',
                POSTHOG_DB_USER: 'user1@domain',
                POSTHOG_DB_PASSWORD: 'strong?password',
                POSTHOG_POSTGRES_HOST: 'my.host',
            }
            const config = getDefaultConfigWithEnv(env)
            expect(config.DATABASE_URL).toEqual('postgres://user1%40domain:strong%3Fpassword@my.host:5432/mydb')
        })

        test('DATABASE_URL takes precedence to individual config options', () => {
            const env = {
                DATABASE_URL: 'my_db_url',
                POSTHOG_DB_NAME: 'mydb',
                POSTHOG_DB_USER: 'user1',
                POSTHOG_DB_PASSWORD: 'strongpassword',
                POSTHOG_POSTGRES_HOST: 'my.host',
            }
            const config = getDefaultConfigWithEnv(env)
            expect(config.DATABASE_URL).toEqual('my_db_url')
        })
    })
})

describe('buildIntegerMatcher', () => {
    test('empty input', () => {
        const matcher = buildIntegerMatcher('', false)
        expect(matcher(2)).toBe(false)
    })
    test('ignores star star when not allowed', () => {
        const matcher = buildIntegerMatcher('*', false)
        expect(matcher(2)).toBe(false)
    })
    test('matches star when allowed', () => {
        const matcher = buildIntegerMatcher('*', true)
        expect(matcher(2)).toBe(true)
    })
    test('can match on a single value', () => {
        const matcher = buildIntegerMatcher('2', true)
        expect(matcher(2)).toBe(true)
        expect(matcher(3)).toBe(false)
    })
    test('can match on several values', () => {
        const matcher = buildIntegerMatcher('2,3,4', true)
        expect(matcher(2)).toBe(true)
        expect(matcher(3)).toBe(true)
        expect(matcher(4)).toBe(true)
        expect(matcher(5)).toBe(false)
    })
})

describe('buildStringMatcher', () => {
    test('empty input', () => {
        const matcher = buildStringMatcher('', false)
        expect(matcher('b')).toBe(false)
    })
    test('ignores star star when not allowed', () => {
        const matcher = buildStringMatcher('*', false)
        expect(matcher('b')).toBe(false)
    })
    test('matches star when allowed', () => {
        const matcher = buildStringMatcher('*', true)
        expect(matcher('b')).toBe(true)
    })
    test('can match on a single value', () => {
        const matcher = buildStringMatcher('b', true)
        expect(matcher('b')).toBe(true)
        expect(matcher('a')).toBe(false)
    })
    test('can match on several values', () => {
        const matcher = buildStringMatcher('b,c,d', true)
        expect(matcher('b')).toBe(true)
        expect(matcher('c')).toBe(true)
        expect(matcher('d')).toBe(true)
        expect(matcher('e')).toBe(false)
    })
})
