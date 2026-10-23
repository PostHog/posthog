import { RedisPoolComponent } from './redis'

describe('RedisPoolComponent', () => {
    it('fails to start when Redis is unreachable', async () => {
        // A non-fatal client gives up after commandTimeout instead of killing the test process.
        const component = new RedisPoolComponent({
            connection: {
                url: '127.0.0.1',
                options: { port: 1, commandTimeout: 100 },
                name: 'unreachable-test',
                exitOnRepeatedErrors: false,
            },
            poolMinSize: 1,
            poolMaxSize: 1,
            acquireTimeoutMillis: 500,
        })

        await expect(component.start()).rejects.toThrow()
    })
})
