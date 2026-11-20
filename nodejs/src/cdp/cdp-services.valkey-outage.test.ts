import { createCdpValkeyShadowPools } from './cdp-services'
import { dualWrite } from './utils/dual-store'

// ioredis waits 50 ms more before each reconnect, so a fatal client passes its error limit of 10 after
// about 2.75 s. Waiting longer shows whether any client of the pool stops the process.
const FATAL_CLIENT_ERROR_WINDOW_MS = 5_000

describe('createCdpValkeyShadowPools with an unreachable Valkey', () => {
    let kill: jest.SpyInstance
    let exit: jest.SpyInstance

    beforeEach(() => {
        kill = jest.spyOn(process, 'kill').mockImplementation(() => true)
        exit = jest.spyOn(process, 'exit').mockImplementation(() => undefined as never)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('keeps the process up, fails shadow calls, and still completes dual writes', async () => {
        const { writer } = createCdpValkeyShadowPools(
            {
                // Nothing listens on port 1, so every connection attempt fails.
                CDP_VALKEY_HOST: '127.0.0.1',
                CDP_VALKEY_PORT: 1,
                CDP_VALKEY_PASSWORD: '',
                CDP_VALKEY_READER_HOST: '',
                CDP_VALKEY_READER_PORT: 1,
                CDP_VALKEY_TLS: false,
                REDIS_POOL_MIN_SIZE: 1,
                REDIS_POOL_MAX_SIZE: 4,
            },
            'test-unreachable-valkey'
        )

        const probes: Promise<unknown>[] = []
        const outageEndsAt = Date.now() + FATAL_CLIENT_ERROR_WINDOW_MS
        while (Date.now() < outageEndsAt && kill.mock.calls.length === 0) {
            probes.push(writer.useClient({ name: 'probe' }, (client) => client.ping()).catch((error) => error))
            await new Promise((resolve) => setTimeout(resolve, 100))
        }

        expect(kill).not.toHaveBeenCalled()
        expect(exit).not.toHaveBeenCalled()
        expect((await Promise.all(probes)).every((outcome) => outcome instanceof Error)).toBe(true)

        let redisWrites = 0
        await dualWrite(
            'hog-masker.test',
            () => Promise.resolve(redisWrites++),
            () => writer.useClient({ name: 'shadow-write' }, (client) => client.set('key', 'value'))
        )
        expect(redisWrites).toBe(1)
    }, 30_000)
})
