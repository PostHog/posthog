import { AddressInfo, Server, Socket, connect, createServer } from 'net'

import { defaultConfig } from '~/common/config/config'
import { RedisV2 } from '~/common/redis/redis-v2'
import { UUIDT } from '~/common/utils/utils'

import { createCdpValkeyShadowPools } from './cdp-services'

const LONGER_THAN_A_FATAL_CLIENT_TAKES_TO_QUIT_MS = 5_000
const PORT_NOTHING_LISTENS_ON = 1
const ONE_SHARED_CONNECTION = { REDIS_POOL_MIN_SIZE: 1, REDIS_POOL_MAX_SIZE: 1 }

const yieldToIo = (): Promise<void> => new Promise((resolve) => setImmediate(resolve))

const shadowConfig = {
    CDP_VALKEY_HOST: '127.0.0.1',
    CDP_VALKEY_PORT: defaultConfig.CDP_VALKEY_PORT,
    CDP_VALKEY_PASSWORD: '',
    CDP_VALKEY_READER_HOST: '',
    CDP_VALKEY_READER_PORT: defaultConfig.CDP_VALKEY_PORT,
    CDP_VALKEY_TLS: false,
    REDIS_POOL_MIN_SIZE: 1,
    REDIS_POOL_MAX_SIZE: 4,
}

describe('createCdpValkeyShadowPools when Valkey is unavailable', () => {
    let kill: jest.SpyInstance
    let exit: jest.SpyInstance

    beforeEach(() => {
        kill = jest.spyOn(process, 'kill').mockImplementation(() => true)
        exit = jest.spyOn(process, 'exit').mockImplementation(() => undefined as never)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    const unreachable = (): RedisV2 =>
        createCdpValkeyShadowPools(
            { ...shadowConfig, CDP_VALKEY_PORT: PORT_NOTHING_LISTENS_ON },
            'test-unreachable-valkey'
        ).writer

    it('keeps the process up while every shadow call fails', async () => {
        const writer = unreachable()

        const probes: Promise<unknown>[] = []
        const outageEndsAt = Date.now() + LONGER_THAN_A_FATAL_CLIENT_TAKES_TO_QUIT_MS
        while (Date.now() < outageEndsAt && kill.mock.calls.length === 0) {
            probes.push(writer.useClient({ name: 'probe' }, (client) => client.ping()).catch((error) => error))
            await new Promise((resolve) => setTimeout(resolve, 100))
        }

        expect(kill).not.toHaveBeenCalled()
        expect(exit).not.toHaveBeenCalled()
        expect((await Promise.all(probes)).every((outcome) => outcome instanceof Error)).toBe(true)
    }, 30_000)

    it('gives a caller that fails open no result instead of an error', async () => {
        const writer = unreachable()

        await expect(
            writer.useClient({ name: 'fail-open-probe', failOpen: true }, (client) => client.ping())
        ).resolves.toBeNull()
        await expect(
            writer.usePipeline({ name: 'fail-open-pipeline', failOpen: true }, (pipeline) => pipeline.ping())
        ).resolves.toBeNull()
    }, 30_000)

    describe('after a connection the pool holds drops', () => {
        let sockets: Socket[]
        let proxy: Server
        let port: number
        let writer: RedisV2

        beforeEach(async () => {
            sockets = []
            proxy = createServer((client) => {
                const upstream = connect(defaultConfig.CDP_VALKEY_PORT, '127.0.0.1')
                sockets.push(client, upstream)
                client.pipe(upstream).pipe(client)
                client.on('error', () => {})
                upstream.on('error', () => {})
            })
            await new Promise<void>((resolve) => proxy.listen(0, '127.0.0.1', resolve))
            port = (proxy.address() as AddressInfo).port
            writer = createCdpValkeyShadowPools(
                { ...shadowConfig, ...ONE_SHARED_CONNECTION, CDP_VALKEY_PORT: port },
                'test-valkey-dropped-connection'
            ).writer
            expect(await writer.useClient({ name: 'warm' }, (client) => client.ping())).toEqual('PONG')

            const closed = new Promise<void>((resolve) => proxy.close(() => resolve()))
            sockets.forEach((socket) => socket.destroy())
            await closed
        })

        afterEach(() => {
            proxy.close()
            sockets.forEach((socket) => socket.destroy())
        })

        const restoreValkey = async (): Promise<void> => {
            await new Promise<void>((resolve) => proxy.listen(port, '127.0.0.1', resolve))
            let pong: unknown = null
            while (pong !== 'PONG') {
                await yieldToIo()
                pong = await writer.useClient({ name: 'recover' }, (client) => client.ping()).catch(() => null)
            }
        }

        it('does not replay a write from the outage once Valkey answers again', async () => {
            const key = `test-valkey-outage-replay/${new UUIDT().toString()}`
            try {
                await expect(
                    writer.useClient({ name: 'outage-write' }, (client) => client.set(key, 'written during the outage'))
                ).rejects.toThrow()

                await restoreValkey()

                expect(await writer.useClient({ name: 'read' }, (client) => client.get(key))).toBeNull()
            } finally {
                await writer.useClient({ name: 'cleanup' }, (client) => client.del(key)).catch(() => null)
            }
        }, 30_000)

        it('fails a pipeline instead of answering it with per-command errors', async () => {
            await expect(
                writer.usePipeline({ name: 'outage-read' }, (pipeline) => pipeline.get('test-valkey-outage-read'))
            ).rejects.toThrow()
        }, 30_000)
    })
})
