import { buildIntegerMatcher, buildStringMatcher, getDefaultConfig, overrideWithEnv } from '../src/config/config'
import { defineConfig } from '../src/config/define-config'

describe('defineConfig', () => {
    test('defaults evaluates factory functions', () => {
        const section = defineConfig({
            HOST: () => 'localhost',
            PORT: () => 8080,
            ENABLED: () => true,
        })

        expect(section.defaults()).toEqual({
            HOST: 'localhost',
            PORT: 8080,
            ENABLED: true,
        })
    })

    test('defaults calls factories lazily on each invocation', () => {
        let counter = 0
        const section = defineConfig({
            VALUE: () => ++counter,
        })

        expect(section.defaults().VALUE).toBe(1)
        expect(section.defaults().VALUE).toBe(2)
    })

    test('nullable types preserve null and undefined defaults', () => {
        const section = defineConfig({
            NULLABLE: (): string | null => null,
            OPTIONAL: (): string | undefined => undefined,
        })
        const defaults = section.defaults()

        expect(defaults.NULLABLE).toBeNull()
        expect(defaults.OPTIONAL).toBeUndefined()
    })

    test('overrideWithEnv works with defineConfig-produced defaults', () => {
        const section = defineConfig({
            SESSION_RECORDING_API_REDIS_HOST: () => '127.0.0.1',
            SESSION_RECORDING_API_REDIS_PORT: () => 6379,
        })
        const fullConfig = { ...getDefaultConfig(), ...section.defaults() }
        const env = {
            SESSION_RECORDING_API_REDIS_HOST: 'redis.prod',
            SESSION_RECORDING_API_REDIS_PORT: '6380',
        }
        const config = overrideWithEnv(fullConfig, env)

        expect(config.SESSION_RECORDING_API_REDIS_HOST).toBe('redis.prod')
        expect(config.SESSION_RECORDING_API_REDIS_PORT).toBe(6380)
    })

    test('session recording config is included in getDefaultConfig', () => {
        const config = getDefaultConfig()

        expect(config.SESSION_RECORDING_API_REDIS_HOST).toBe('127.0.0.1')
        expect(config.SESSION_RECORDING_API_REDIS_PORT).toBe(6379)
        expect(config.SESSION_RECORDING_LOCAL_DIRECTORY).toBe('.tmp/sessions')
        expect(config.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS).toBe(600)
        expect(config.SESSION_RECORDING_OVERFLOW_ENABLED).toBe(false)
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
        const config = overrideWithEnv(getDefaultConfig(), env)

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
        const config = overrideWithEnv(getDefaultConfig(), env)

        expect(config.INSTRUMENT_THREAD_PERFORMANCE).toEqual(true)
        expect(config.TASK_TIMEOUT).toEqual(3008.12)
    })

    describe('DATABASE_URL', () => {
        test('Error if DATABASE_URL is not set AND POSTHOG_DB_NAME is not set', () => {
            const env = {
                DATABASE_URL: '',
                POSTHOG_DB_NAME: '',
            }
            expect(() => overrideWithEnv(getDefaultConfig(), env)).toThrow(
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
            const config = overrideWithEnv(getDefaultConfig(), env)
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
            const config = overrideWithEnv(getDefaultConfig(), env)
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
