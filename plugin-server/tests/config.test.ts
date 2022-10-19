import { getDefaultConfig, overrideWithEnv } from '../src/config/config'

describe('config', () => {
    test('overrideWithEnv 1', () => {
        const defaultConfig = getDefaultConfig()
        const env = {
            CLICKHOUSE_SECURE: 'false',
            TASK_TIMEOUT: '3008',
            CLICKHOUSE_HOST: '0.0.0.0',
            BASE_DIR: undefined,
        }
        const config = overrideWithEnv(getDefaultConfig(), env)

        expect(config.CLICKHOUSE_SECURE).toEqual(false)
        expect(config.TASK_TIMEOUT).toEqual(3008)
        expect(config.CLICKHOUSE_HOST).toEqual('0.0.0.0')
        expect(config.BASE_DIR).toEqual(defaultConfig.BASE_DIR)
    })

    test('overrideWithEnv 2', () => {
        const env = {
            CLICKHOUSE_SECURE: '1',
            TASK_TIMEOUT: '3008.12',
        }
        const config = overrideWithEnv(getDefaultConfig(), env)

        expect(config.CLICKHOUSE_SECURE).toEqual(true)
        expect(config.TASK_TIMEOUT).toEqual(3008.12)
    })

    describe('DATABASE_URL', () => {
        test('Error if DATABASE_URL is not set AND POSTHOG_DB_NAME is not set', () => {
            const env = {
                DATABASE_URL: '',
                POSTHOG_DB_NAME: '',
            }
            expect(() => overrideWithEnv(getDefaultConfig(), env)).toThrowError(
                'You must specify either DATABASE_URL or the database options POSTHOG_DB_NAME, POSTHOG_DB_USER, POSTHOG_DB_PASSWORD, POSTHOG_POSTGRES_HOST, POSTHOG_POSTGRES_PORT!'
            )
        })

        test('Set DATABASE_URL to a string composed of connection options if DATABASE_URL is not explictly set', () => {
            const env = {
                DATABASE_URL: '',
                POSTHOG_DB_NAME: 'mydb',
                POSTHOG_DB_USER: 'user1',
                POSTHOG_DB_PASSWORD: 'strongpassword',
                POSTHOG_POSTGRES_HOST: 'my.host',
            }
            const config = overrideWithEnv(getDefaultConfig(), env)
            expect(config.DATABASE_URL).toEqual('postgres://user1:strongpassword@my.host:5432/mydb')
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
