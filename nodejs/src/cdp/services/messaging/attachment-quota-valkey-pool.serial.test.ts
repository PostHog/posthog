import net from 'net'

import { createAttachmentQuotaValkeyPool } from './attachment-quota-valkey-pool'

// The dev and CI stack's Valkey, the one the other CDP Valkey tests use.
const VALKEY_HOST = '127.0.0.1'
const VALKEY_PORT = 6390

type SilenceableProxy = { port: number; silenceOpenConnections: () => void; close: () => Promise<void> }

// Forwards every connection to Valkey. Silencing stops forwarding on the connections open at that moment,
// so their commands get no answer, while connections opened later work again.
async function startSilenceableProxy(): Promise<SilenceableProxy> {
    const open = new Map<net.Socket, net.Socket>()
    const server = net.createServer((client) => {
        const upstream = net.connect(VALKEY_PORT, VALKEY_HOST)
        const close = (): void => {
            open.delete(client)
            client.destroy()
            upstream.destroy()
        }
        client.on('error', close).on('close', close)
        upstream.on('error', close).on('close', close)
        client.pipe(upstream)
        upstream.pipe(client)
        open.set(client, upstream)
    })
    await new Promise<void>((resolve) => server.listen(0, VALKEY_HOST, resolve))

    return {
        port: (server.address() as net.AddressInfo).port,
        silenceOpenConnections: () => {
            for (const [client, upstream] of open) {
                client.unpipe(upstream)
            }
        },
        close: async () => {
            for (const [client, upstream] of open) {
                client.destroy()
                upstream.destroy()
            }
            await new Promise<void>((resolve) => server.close(() => resolve()))
        },
    }
}

describe('attachment quota Valkey pool', () => {
    let proxy: SilenceableProxy

    beforeEach(async () => {
        proxy = await startSilenceableProxy()
    })

    afterEach(async () => {
        await proxy.close()
    })

    it('replaces a connection that stopped answering instead of handing it out again', async () => {
        const pool = createAttachmentQuotaValkeyPool({
            CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_HOST: VALKEY_HOST,
            CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_PORT: proxy.port,
            CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_PASSWORD: '',
            CDP_EMAIL_ATTACHMENTS_QUOTA_VALKEY_TLS: false,
            REDIS_POOL_MAX_SIZE: 1,
        })!
        const ping = (): Promise<string | null> => pool.useClient({ name: 'test-ping' }, (client) => client.ping())

        expect(await ping()).toBe('PONG')

        proxy.silenceOpenConnections()
        await expect(ping()).rejects.toThrow()

        expect(await ping()).toBe('PONG')
    })
})
