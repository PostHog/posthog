import { execFile } from 'child_process'
import { join } from 'path'
import { promisify } from 'util'

import { getExternalRequestConfig } from '~/common/config'
import {
    buildIntegerMatcher,
    buildStringMatcher,
    getDefaultConfig,
    overrideConfigWithEnv,
    overrideWithEnv,
} from '~/common/config/config'
import { MISSING_DATABASE_URL_MESSAGE } from '~/common/config/database-url'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'

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

    function readExternalRequestTimeout(value: string): number {
        const previous = process.env.EXTERNAL_REQUEST_TIMEOUT_MS
        process.env.EXTERNAL_REQUEST_TIMEOUT_MS = value
        try {
            return getExternalRequestConfig().EXTERNAL_REQUEST_TIMEOUT_MS
        } finally {
            if (previous === undefined) {
                delete process.env.EXTERNAL_REQUEST_TIMEOUT_MS
            } else {
                process.env.EXTERNAL_REQUEST_TIMEOUT_MS = previous
            }
        }
    }

    type Row = [value: string, expected: number | 'default']
    const everyReader: Row[] = [
        ['"3008"', 3008],
        ["'3008'", 3008],
        ['" 3008.12 "', 3008.12],
        ['.5', 0.5],
        ['"3008', 'default'],
        ['abc', 'default'],
        ['Infinity', 'default'],
    ]
    const overrideRows: Row[] = [
        ['10ms', 10],
        ['', 'default'],
        [' ', 'default'],
    ]

    describe.each<[string, (value: string) => number, number, Row[]]>([
        [
            'overrideWithEnv',
            (value) => overrideWithEnv(getDefaultConfig(), { TASK_TIMEOUT: value }).TASK_TIMEOUT,
            30,
            overrideRows,
        ],
        [
            'overrideConfigWithEnv',
            (value) => overrideConfigWithEnv({ TASK_TIMEOUT: 30 }, { TASK_TIMEOUT: value }).TASK_TIMEOUT,
            30,
            overrideRows,
        ],
        [
            'getExternalRequestConfig',
            readExternalRequestTimeout,
            3000,
            [
                ['0x10', 16],
                ['', 0],
                ['""', 'default'],
                ['3000ms', 'default'],
            ],
        ],
    ])('%s', (_reader, read, defaultValue, ownRows) => {
        test.each([...everyReader, ...ownRows])('reads the env value %p as %p', (value, expected) => {
            expect(read(value)).toEqual(expected === 'default' ? defaultValue : expected)
        })
    })

    test('a service started with quoted and unparsable numbers reads the quoted one and logs the other', async () => {
        const { stdout } = await promisify(execFile)(
            join(__dirname, '../node_modules/.bin/tsx'),
            [
                '-e',
                "import('~/common/config/config').then(({ defaultConfig: c }) => console.log(JSON.stringify({ CDP_CYCLOTRON_BATCH_DELAY_MAX_MS: c.CDP_CYCLOTRON_BATCH_DELAY_MAX_MS, TASK_TIMEOUT: c.TASK_TIMEOUT })))",
            ],
            {
                cwd: join(__dirname, '..'),
                env: {
                    ...process.env,
                    NODE_ENV: 'production',
                    DEBUG: '',
                    LOG_LEVEL: 'info',
                    CDP_CYCLOTRON_BATCH_DELAY_MAX_MS: '"1000"',
                    TASK_TIMEOUT: 'abc',
                },
            }
        )
        const lines = stdout
            .split('\n')
            .filter((line) => line.startsWith('{'))
            .map((line) => parseJSON(line))

        expect(lines).toContainEqual({ CDP_CYCLOTRON_BATCH_DELAY_MAX_MS: 1000, TASK_TIMEOUT: 30 })
        expect(lines).toContainEqual(
            expect.objectContaining({
                level: 'error',
                msg: expect.stringContaining('TASK_TIMEOUT'),
                value: 'abc',
                default: 30,
            })
        )
    }, 60_000)

    test.each([
        ['true', true],
        ['1', false],
        ['yes', false],
        ['TRUE', false],
        [undefined, false],
    ])('turns sandbox email sending on only for exactly "true" (got %s)', (value, expected) => {
        const config = overrideWithEnv(getDefaultConfig(), { WORKFLOWS_SANDBOX_SENDER_ENABLED: value })

        expect(config.WORKFLOWS_SANDBOX_SENDER_ENABLED).toBe(expected)
    })

    describe('DATABASE_URL', () => {
        test('Error only when Postgres is opened if DATABASE_URL is not set AND POSTHOG_DB_NAME is not set', () => {
            const env = {
                DATABASE_URL: '',
                POSTHOG_DB_NAME: '',
            }
            const config = overrideWithEnv(getDefaultConfig(), env)

            expect(config.DATABASE_URL).toEqual('')
            expect(() => new PostgresRouter(config)).toThrow(MISSING_DATABASE_URL_MESSAGE)
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
