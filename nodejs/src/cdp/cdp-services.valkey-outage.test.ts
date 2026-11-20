import { execFile } from 'child_process'
import { AddressInfo, Server, Socket, connect, createServer } from 'net'
import path from 'path'

import { defaultConfig } from '~/common/config/config'
import { RedisV2 } from '~/common/redis/redis-v2'
import { UUIDT } from '~/common/utils/utils'

import { createCdpValkeyShadowPools } from './cdp-services'

const LONGER_THAN_A_FATAL_CLIENT_TAKES_TO_QUIT_MS = 5_000
const PORT_NOTHING_LISTENS_ON = 1
const HALF_THE_SHADOW_COMMAND_TIMEOUT_MS = 500
const ONE_SHARED_CONNECTION = { REDIS_POOL_MIN_SIZE: 1, REDIS_POOL_MAX_SIZE: 1 }

const NODEJS_ROOT = path.resolve(__dirname, '../..')

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

const shadowCallsAgainstAnUnreachableValkey = `
import { createCdpValkeyShadowPools } from './src/cdp/cdp-services'

const { writer } = createCdpValkeyShadowPools(
    ${JSON.stringify({ ...shadowConfig, CDP_VALKEY_PORT: PORT_NOTHING_LISTENS_ON })},
    'test-unreachable-valkey'
)

const callUntilTheOutageEnds = async () => {
    const outcomes = new Set()
    const outageEndsAt = Date.now() + ${LONGER_THAN_A_FATAL_CLIENT_TAKES_TO_QUIT_MS}
    while (Date.now() < outageEndsAt) {
        outcomes.add(await writer.useClient({ name: 'probe' }, (client) => client.ping()).then(() => 'answered', () => 'failed'))
        await new Promise((resolve) => setTimeout(resolve, 100))
    }
    process.stdout.write('\\noutcomes=' + [...outcomes].join(',') + '\\n')
    process.exit(0)
}

void callUntilTheOutageEnds()
`

type ChildProcessOutcome = { code: number | null; signal: NodeJS.Signals | null; stdout: string }

const runInChildProcess = (script: string): Promise<ChildProcessOutcome> =>
    new Promise((resolve) => {
        execFile(
            process.execPath,
            ['--import', 'tsx', '--input-type=module', '--eval', script],
            {
                cwd: NODEJS_ROOT,
                env: { ...process.env, NODE_OPTIONS: '' },
                timeout: 30_000,
                maxBuffer: 16 * 1024 * 1024,
            },
            (error, stdout) =>
                resolve({
                    code: error ? (typeof error.code === 'number' ? error.code : null) : 0,
                    signal: error?.signal ?? null,
                    stdout,
                })
        )
    })

describe('createCdpValkeyShadowPools when Valkey is unavailable', () => {
    beforeEach(() => {
        jest.spyOn(process, 'kill').mockImplementation(() => true)
        jest.spyOn(process, 'exit').mockImplementation(() => undefined as never)
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
        const child = await runInChildProcess(shadowCallsAgainstAnUnreachableValkey)

        expect(child).toEqual({ code: 0, signal: null, stdout: expect.stringMatching(/^outcomes=failed$/m) })
    }, 60_000)

    it('gives a caller that fails open no result instead of an error', async () => {
        const writer = unreachable()

        await expect(
            writer.useClient({ name: 'fail-open-probe', failOpen: true }, (client) => client.ping())
        ).resolves.toBeNull()
        await expect(
            writer.usePipeline({ name: 'fail-open-pipeline', failOpen: true }, (pipeline) => pipeline.ping())
        ).resolves.toBeNull()
    }, 30_000)

    describe('with Valkey behind a proxy that the test controls', () => {
        type ProxiedConnection = { client: Socket; upstream: Socket; forwarding: boolean }
        let connections: ProxiedConnection[]
        let proxy: Server
        let port: number
        let writer: RedisV2

        beforeEach(async () => {
            connections = []
            proxy = createServer((client) => {
                const upstream = connect(defaultConfig.CDP_VALKEY_PORT, '127.0.0.1')
                const connection = { client, upstream, forwarding: true }
                connections.push(connection)
                client.on('data', (data) => connection.forwarding && upstream.write(data))
                upstream.pipe(client)
                client.on('error', () => {})
                upstream.on('error', () => {})
            })
            await new Promise<void>((resolve) => proxy.listen(0, '127.0.0.1', resolve))
            port = (proxy.address() as AddressInfo).port
            writer = createCdpValkeyShadowPools(
                { ...shadowConfig, ...ONE_SHARED_CONNECTION, CDP_VALKEY_PORT: port },
                'test-valkey-behind-proxy'
            ).writer
            expect(await writer.useClient({ name: 'warm' }, (client) => client.ping())).toEqual('PONG')
        })

        afterEach(() => {
            proxy.close()
            connections.forEach(({ client, upstream }) => [client, upstream].forEach((socket) => socket.destroy()))
        })

        const dropConnections = async (): Promise<void> => {
            const closed = new Promise<void>((resolve) => proxy.close(() => resolve()))
            connections.forEach(({ client, upstream }) => [client, upstream].forEach((socket) => socket.destroy()))
            await closed
        }

        const stopAnsweringOpenConnections = (): void => {
            connections.forEach((connection) => (connection.forwarding = false))
        }

        const restoreValkey = async (): Promise<void> => {
            await new Promise<void>((resolve) => proxy.listen(port, '127.0.0.1', resolve))
            const giveUpAt = Date.now() + 10_000
            let pong: unknown = null
            while (pong !== 'PONG') {
                if (Date.now() > giveUpAt) {
                    throw new Error('the shadow pool did not reconnect to Valkey')
                }
                await yieldToIo()
                pong = await writer.useClient({ name: 'recover' }, (client) => client.ping()).catch(() => null)
            }
        }

        const readBack = async (key: string): Promise<string | null> => {
            const value = await writer.useClient({ name: 'read' }, (client) => client.get(key))
            await writer.useClient({ name: 'cleanup' }, (client) => client.del(key))
            return value
        }

        it('does not replay a write issued while the connection is down', async () => {
            const key = `test-valkey-outage-replay/${new UUIDT().toString()}`
            await dropConnections()

            await expect(
                writer.useClient({ name: 'outage-write' }, (client) => client.set(key, 'written during the outage'))
            ).rejects.toThrow()
            await restoreValkey()

            expect(await readBack(key)).toBeNull()
        }, 30_000)

        it('fails a command on a dropped connection without waiting for the command timeout', async () => {
            const clientSawTheDrop = writer.useClient(
                { name: 'watch-drop' },
                (client) => new Promise((resolve) => client.once('close', resolve))
            )
            await dropConnections()
            await clientSawTheDrop

            const startedAt = Date.now()
            await expect(writer.useClient({ name: 'outage-ping' }, (client) => client.ping())).rejects.toThrow()

            expect(Date.now() - startedAt).toBeLessThan(HALF_THE_SHADOW_COMMAND_TIMEOUT_MS)
        }, 30_000)

        it('does not resend a write that was in flight when the connection dropped', async () => {
            const key = `test-valkey-outage-resend/${new UUIDT().toString()}`
            stopAnsweringOpenConnections()

            await expect(
                writer.useClient({ name: 'stalled-write' }, (client) => client.set(key, 'in flight at the drop'))
            ).rejects.toThrow()
            await dropConnections()
            await restoreValkey()

            expect(await readBack(key)).toBeNull()
        }, 30_000)

        it('answers through a new connection after a command stalls', async () => {
            stopAnsweringOpenConnections()
            await expect(writer.useClient({ name: 'stalled' }, (client) => client.ping())).rejects.toThrow()

            expect(await writer.useClient({ name: 'after-stall' }, (client) => client.ping())).toEqual('PONG')
        }, 30_000)
    })
})
