import { RedisConnectionConfig, RedisPoolComponent } from './redis'

const giveUpBeforeErrorLimit = (attempt: number): number | null => (attempt < 5 ? 25 : null)

const unreachableRedis = (overrides: Partial<RedisConnectionConfig>): RedisConnectionConfig => ({
    url: '127.0.0.1',
    options: { port: 1, commandTimeout: 100, retryStrategy: giveUpBeforeErrorLimit },
    name: 'unreachable-test',
    ...overrides,
})

describe('RedisPoolComponent', () => {
    it('fails to start when Redis is unreachable', async () => {
        const component = new RedisPoolComponent({
            connection: unreachableRedis({}),
            poolMinSize: 1,
            poolMaxSize: 1,
            acquireTimeoutMillis: 200,
        })

        await expect(component.start()).rejects.toThrow()
    })

    it('starts a non-fatal pool when Redis is unreachable', async () => {
        const component = new RedisPoolComponent({
            connection: unreachableRedis({ exitOnRepeatedErrors: false }),
            poolMinSize: 1,
            poolMaxSize: 1,
        })

        const started = await component.start()
        await started.stop()
    })
})
