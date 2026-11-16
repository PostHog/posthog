import { RedisV2 } from '~/common/redis/redis-v2'

import { createCdpReaderRedisPool, createCdpValkeyShadowPools } from './cdp-services'

type FakeRedisServer = {
    password: string
    data: Record<string, string>
    pingError?: Error
    commands: string[]
}

type FakeRedisNetwork = {
    servers: Map<string, FakeRedisServer>
    connections: string[]
}

jest.mock('ioredis', () => {
    const network: FakeRedisNetwork = { servers: new Map(), connections: [] }

    class FakeRedis {
        static network = network
        private readonly address: string

        constructor(
            host: string,
            private readonly options: { port?: number; password?: string }
        ) {
            this.address = `${host}:${options.port ?? 6379}`
            network.connections.push(this.address)
        }

        on(): this {
            return this
        }

        defineCommand(): void {}

        async info(): Promise<string> {
            await this.server()
            return ''
        }

        async ping(): Promise<string> {
            const server = await this.server()
            server.commands.push('PING')
            if (server.pingError) {
                throw server.pingError
            }
            return 'PONG'
        }

        async get(key: string): Promise<string | null> {
            const server = await this.server()
            server.commands.push('GET')
            return server.data[key] ?? null
        }

        quit(): Promise<string> {
            return Promise.resolve('OK')
        }

        disconnect(): void {}

        private async server(): Promise<FakeRedisServer> {
            const server = network.servers.get(this.address)
            if (!server) {
                // ioredis keeps reconnecting to an unreachable address, so its commands never settle.
                return new Promise(() => {})
            }
            await new Promise((resolve) => setImmediate(resolve))
            if (server.password !== this.options.password) {
                throw new Error('WRONGPASS invalid username-password pair or user is disabled.')
            }
            return server
        }
    }

    return FakeRedis
})

const { network } = jest.requireMock<{ network: FakeRedisNetwork }>('ioredis')

const mockWriterPool = { useClient: jest.fn(), usePipeline: jest.fn() } as unknown as RedisV2

const baseConfig = {
    CDP_REDIS_HOST: 'cdp-writer.internal',
    CDP_REDIS_PORT: 6379,
    CDP_REDIS_PASSWORD: 'secret',
    CDP_REDIS_READER_HOST: '',
    CDP_REDIS_READER_PORT: 6379,
    REDIS_URL: 'rediss://:password@fallback-host:6379',
    REDIS_POOL_MIN_SIZE: 1,
    // With one connection, a command a test sends waits until the startup ping has finished.
    REDIS_POOL_MAX_SIZE: 1,
}

const readerConfig = { ...baseConfig, CDP_REDIS_READER_HOST: 'cdp-reader.internal', CDP_REDIS_READER_PORT: 6380 }

const readSource = (pool: RedisV2): Promise<string | null> =>
    pool.useClient({ name: 'test-read', deadlineMs: 1000 }, (client) => client.get('source'))

const serverAt = (address: string): FakeRedisServer => {
    const server = network.servers.get(address)
    if (!server) {
        throw new Error(`no fake Redis server at ${address}`)
    }
    return server
}

beforeEach(() => {
    network.connections.length = 0
    network.servers.clear()
    network.servers.set('cdp-writer.internal:6379', { password: 'secret', data: { source: 'writer' }, commands: [] })
    network.servers.set('cdp-reader.internal:6380', { password: 'secret', data: { source: 'reader' }, commands: [] })
})

describe('createCdpReaderRedisPool', () => {
    it('reads from the reader host when CDP_REDIS_READER_HOST is set', async () => {
        const reader = createCdpReaderRedisPool(readerConfig, mockWriterPool, 'test-redis')

        await expect(readSource(reader)).resolves.toBe('reader')
    })

    it('pings the reader before it serves the first command', async () => {
        const reader = createCdpReaderRedisPool(readerConfig, mockWriterPool, 'test-redis')

        await readSource(reader)

        expect(serverAt('cdp-reader.internal:6380').commands).toEqual(['PING', 'GET'])
    })

    it('logs an error if the reader health check fails', async () => {
        const pingError = new Error('LOADING Redis is loading the dataset in memory')
        serverAt('cdp-reader.internal:6380').pingError = pingError
        const logSpy = jest.spyOn(require('~/common/utils/logger').logger, 'error')

        const reader = createCdpReaderRedisPool(readerConfig, mockWriterPool, 'test-redis')
        await readSource(reader)

        expect(logSpy).toHaveBeenCalledWith(
            '🔌',
            expect.stringContaining('failed startup health check'),
            expect.objectContaining({ err: pingError })
        )
    })

    it('falls back to writer pool when CDP_REDIS_READER_HOST is not set', () => {
        const config = { ...baseConfig, CDP_REDIS_READER_HOST: '' }

        const result = createCdpReaderRedisPool(config, mockWriterPool, 'test-redis')

        expect(result).toBe(mockWriterPool)
        expect(network.connections).toEqual([])
    })

    it('does not leak credentials from REDIS_URL in fallback log', () => {
        const logSpy = jest.spyOn(require('~/common/utils/logger').logger, 'info')
        const config = {
            ...baseConfig,
            CDP_REDIS_HOST: '',
            CDP_REDIS_READER_HOST: '',
            REDIS_URL: 'rediss://:supersecret@prod-redis.internal:6379',
        }

        createCdpReaderRedisPool(config, mockWriterPool, 'test-redis')

        const logMessage = logSpy.mock.calls[0]?.[1] as string
        expect(logMessage).not.toContain('supersecret')
        expect(logMessage).toContain('prod-redis.internal')
    })
})

describe('createCdpValkeyShadowPools', () => {
    const valkeyConfig = {
        CDP_VALKEY_HOST: 'cdp-valkey.internal',
        CDP_VALKEY_PORT: 6379,
        CDP_VALKEY_PASSWORD: 'secret',
        CDP_VALKEY_READER_HOST: '',
        CDP_VALKEY_READER_PORT: 6379,
        CDP_VALKEY_TLS: false,
        REDIS_POOL_MIN_SIZE: 1,
        REDIS_POOL_MAX_SIZE: 4,
    }

    it('throws when CDP_VALKEY_HOST is unset', () => {
        expect(() => createCdpValkeyShadowPools({ ...valkeyConfig, CDP_VALKEY_HOST: '' }, 'test-valkey')).toThrow(
            'CDP_VALKEY_HOST is required'
        )
        expect(network.connections).toEqual([])
    })
})
