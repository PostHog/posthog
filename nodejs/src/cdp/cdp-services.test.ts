import { RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import { createCdpReaderRedisPool, createCdpValkeyShadowPools } from './cdp-services'

type FakeRedisServer = {
    password: string
    data: Record<string, string>
    pingError?: Error
}

type FakeRedisNetwork = {
    servers: Map<string, FakeRedisServer>
    connections: string[]
    reconnects: Array<() => void>
}

jest.mock('ioredis', () => {
    const network: FakeRedisNetwork = { servers: new Map(), connections: [], reconnects: [] }

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
            if (server.pingError) {
                throw server.pingError
            }
            return 'PONG'
        }

        async get(key: string): Promise<string | null> {
            const server = await this.server()
            return server.data[key] ?? null
        }

        quit(): Promise<string> {
            return Promise.resolve('OK')
        }

        disconnect(): void {}

        private async server(): Promise<FakeRedisServer> {
            const server = network.servers.get(this.address)
            if (!server) {
                await this.waitUntilReachable()
                return this.server()
            }
            await new Promise((resolve) => setImmediate(resolve))
            if (server.password !== this.options.password) {
                throw new Error('WRONGPASS invalid username-password pair or user is disabled.')
            }
            return server
        }

        private waitUntilReachable(): Promise<void> {
            return new Promise((reconnect) => network.reconnects.push(reconnect))
        }
    }

    return FakeRedis
})

const { network } = jest.requireMock<{ network: FakeRedisNetwork }>('ioredis')

const mockWriterPool = { useClient: jest.fn(), usePipeline: jest.fn() } as unknown as RedisV2

const SINGLE_CONNECTION_SO_STARTUP_PING_RUNS_FIRST = 1

const baseConfig = {
    CDP_REDIS_HOST: 'cdp-writer.internal',
    CDP_REDIS_PORT: 6379,
    CDP_REDIS_PASSWORD: 'secret',
    CDP_REDIS_READER_HOST: '',
    CDP_REDIS_READER_PORT: 6379,
    REDIS_URL: 'rediss://:password@fallback-host:6379',
    REDIS_POOL_MIN_SIZE: 1,
    REDIS_POOL_MAX_SIZE: SINGLE_CONNECTION_SO_STARTUP_PING_RUNS_FIRST,
}

const readerConfig = { ...baseConfig, CDP_REDIS_READER_HOST: 'cdp-reader.internal', CDP_REDIS_READER_PORT: 6380 }

const READER = 'cdp-reader.internal:6380'

const readSource = (pool: RedisV2, deadlineMs = 1000): Promise<string | null> =>
    pool.useClient({ name: 'test-read', deadlineMs }, (client) => client.get('source'))

const connectionsTo = (address: string): number => network.connections.filter((a) => a === address).length

const bringBack = (address: string, server: FakeRedisServer): void => {
    network.servers.set(address, server)
    network.reconnects.splice(0).forEach((reconnect) => reconnect())
}

const serverAt = (address: string): FakeRedisServer => {
    const server = network.servers.get(address)
    if (!server) {
        throw new Error(`no fake Redis server at ${address}`)
    }
    return server
}

beforeEach(() => {
    network.connections.length = 0
    network.reconnects.length = 0
    network.servers.clear()
    network.servers.set('cdp-writer.internal:6379', { password: 'secret', data: { source: 'writer' } })
    network.servers.set(READER, { password: 'secret', data: { source: 'reader' } })
})

describe('createCdpReaderRedisPool', () => {
    it('reads from the reader host when CDP_REDIS_READER_HOST is set', async () => {
        const reader = createCdpReaderRedisPool(readerConfig, mockWriterPool, 'test-redis')

        await expect(readSource(reader)).resolves.toBe('reader')
    })

    it('keeps REDIS_POOL_MIN_SIZE reader connections open and opens up to REDIS_POOL_MAX_SIZE under load', async () => {
        const config = { ...readerConfig, REDIS_POOL_MIN_SIZE: 2, REDIS_POOL_MAX_SIZE: 3 }

        const reader = createCdpReaderRedisPool(config, mockWriterPool, 'test-redis')
        expect(connectionsTo(READER)).toBe(2)

        await Promise.all(Array.from({ length: config.REDIS_POOL_MAX_SIZE + 1 }, () => readSource(reader)))
        expect(connectionsTo(READER)).toBe(config.REDIS_POOL_MAX_SIZE)
    })

    it('names the reader pool in the deadline error when the reader does not answer', async () => {
        const readerServer = serverAt(READER)
        network.servers.delete(READER)

        const reader = createCdpReaderRedisPool(readerConfig, mockWriterPool, 'test-redis')

        await expect(readSource(reader, 100)).rejects.toThrow('test-redis-reader')
        bringBack(READER, readerServer)
        await expect(readSource(reader)).resolves.toBe('reader')
    })

    it('warns when the startup ping waits five seconds on a reader that does not answer', async () => {
        jest.useFakeTimers({ doNotFake: ['setImmediate', 'nextTick', 'queueMicrotask'] })
        try {
            const readerServer = serverAt(READER)
            network.servers.delete(READER)
            const warnSpy = jest.spyOn(logger, 'warn')
            const warnings = (): unknown[] => warnSpy.mock.calls.map(([, message]) => message)
            const startupPingDelayed = expect.stringContaining('startup-ping delayed')

            const reader = createCdpReaderRedisPool(readerConfig, mockWriterPool, 'test-redis')

            jest.advanceTimersByTime(4999)
            expect(warnings()).not.toContainEqual(startupPingDelayed)
            jest.advanceTimersByTime(1)
            expect(warnings()).toContainEqual(startupPingDelayed)
            bringBack(READER, readerServer)
            await expect(readSource(reader)).resolves.toBe('reader')
        } finally {
            jest.useRealTimers()
        }
    })

    it('logs an error if the reader health check fails', async () => {
        const pingError = new Error('LOADING Redis is loading the dataset in memory')
        serverAt(READER).pingError = pingError
        const logSpy = jest.spyOn(logger, 'error')

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
        const logSpy = jest.spyOn(logger, 'info')
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
