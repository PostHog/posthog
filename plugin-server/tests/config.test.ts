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
})
