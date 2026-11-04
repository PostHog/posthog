import { Socket, createServer } from 'net'

import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { createRedisFromConfig } from '~/common/utils/db/redis'
import { TeamManager } from '~/common/utils/team-manager'
import { killGracefully } from '~/common/utils/utils'

import { MAX_OPEN_STORE_CALLS, SandboxEmailSender, sandboxBlockedEventRedisConfig } from './sandbox-email-sender'

jest.mock('~/common/utils/utils', () => ({
    ...jest.requireActual('~/common/utils/utils'),
    killGracefully: jest.fn(),
}))

// Answers the connection handshake and never answers SET, the way a store that stopped responding behaves.
function startStalledStore(): Promise<{ port: number; stalledCommands: () => number; stop: () => void }> {
    let stalled = 0
    const sockets: Socket[] = []
    const server = createServer((socket) => {
        sockets.push(socket)
        let buffered = ''
        socket.on('data', (chunk) => {
            buffered += chunk.toString('latin1')
            for (;;) {
                const lines = buffered.split('\r\n')
                const argc = Number(lines[0]?.slice(1))
                if (!lines[0]?.startsWith('*') || lines.length < 2 * argc + 2) {
                    return
                }
                const name = lines[2].toUpperCase()
                buffered = lines.slice(2 * argc + 1).join('\r\n')
                if (name === 'SET') {
                    stalled++
                } else if (name === 'INFO') {
                    socket.write('$24\r\nloading:0\r\nrole:master\r\n\r\n')
                } else {
                    socket.write('+OK\r\n')
                }
            }
        })
    })
    return new Promise((resolve) =>
        server.listen(0, '127.0.0.1', () =>
            resolve({
                port: (server.address() as { port: number }).port,
                stalledCommands: () => stalled,
                stop: () => {
                    sockets.forEach((socket) => socket.destroy())
                    server.close()
                },
            })
        )
    )
}

describe('sandboxBlockedEventRedisConfig', () => {
    it('keeps the worker running when Redis refuses its connections', async () => {
        const { connection } = sandboxBlockedEventRedisConfig({
            url: '127.0.0.1',
            // More reconnect attempts than a fatal client tolerates before it stops the process.
            options: { port: 1, commandTimeout: 5000, retryStrategy: (attempt) => (attempt < 15 ? 5 : null) },
            name: 'sandbox-blocked-event-test',
        })

        await expect(createRedisFromConfig(connection)).rejects.toThrow()
        expect(killGracefully).not.toHaveBeenCalled()
    })

    it('sends no more store commands than it has slots while the store does not answer', async () => {
        const store = await startStalledStore()
        try {
            const sender = new SandboxEmailSender(
                {
                    enabled: true,
                    tenantName: 'sandbox',
                    configurationSetName: 'sandbox',
                    fromAddress: 'sender@example.com',
                    dailyTeamCap: '1',
                    dailyRecipientCap: '1',
                },
                { getTeam: () => Promise.resolve(null) } as unknown as TeamManager,
                createRedisV2PoolFromConfig(
                    sandboxBlockedEventRedisConfig({
                        url: '127.0.0.1',
                        // Without a retry limit the clients reconnect forever after the store stops, and Jest never exits.
                        options: { port: store.port, retryStrategy: () => null },
                        name: 'sandbox-blocked-event-stalled-test',
                    })
                ),
                null
            )
            const blockEveryProject = (): Promise<void[]> =>
                Promise.all(
                    Array.from({ length: MAX_OPEN_STORE_CALLS }, (_, index) =>
                        sender.captureBlocked(index + 1, false, 'recipient_not_member', 1)
                    )
                )

            await blockEveryProject()
            await blockEveryProject()

            expect(store.stalledCommands()).toBe(MAX_OPEN_STORE_CALLS)
        } finally {
            store.stop()
        }
    })
})
