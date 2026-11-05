import { Socket, createServer } from 'net'

import { createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { createRedisFromConfig } from '~/common/utils/db/redis'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'
import { killGracefully } from '~/common/utils/utils'

import { MAX_OPEN_STORE_CALLS, SandboxEmailSender, sandboxBlockedEventRedisConfig } from './sandbox-email-sender'

jest.mock('~/common/utils/utils', () => ({
    ...jest.requireActual('~/common/utils/utils'),
    killGracefully: jest.fn(),
}))
jest.mock('~/common/utils/posthog', () => ({
    ...jest.requireActual('~/common/utils/posthog'),
    captureTeamEvent: jest.fn(),
}))

type FakeStore = { port: number; setCommands: () => number; answer: () => void; stop: () => void }

function startStore({ answering }: { answering: boolean }): Promise<FakeStore> {
    let setCommands = 0
    let answerSet = answering
    const unanswered: Socket[] = []
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
                    setCommands++
                    if (answerSet) {
                        socket.write('+OK\r\n')
                    } else {
                        unanswered.push(socket)
                    }
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
                setCommands: () => setCommands,
                answer: () => {
                    answerSet = true
                    unanswered.splice(0).forEach((socket) => socket.write('+OK\r\n'))
                },
                stop: () => {
                    sockets.forEach((socket) => socket.destroy())
                    server.close()
                },
            })
        )
    )
}

function senderOn(store: FakeStore, getTeam: jest.Mock): SandboxEmailSender {
    return new SandboxEmailSender(
        {
            enabled: true,
            tenantName: 'sandbox',
            configurationSetName: 'sandbox',
            fromAddress: 'sender@example.com',
            dailyTeamCap: '1',
            dailyRecipientCap: '1',
        },
        { getTeam } as unknown as TeamManager,
        createRedisV2PoolFromConfig(
            sandboxBlockedEventRedisConfig({
                url: '127.0.0.1',
                options: { port: store.port, retryStrategy: () => null },
                name: 'sandbox-blocked-event-store-test',
            })
        ),
        null,
        { isPaused: () => Promise.resolve(false) }
    )
}

const blockProjects = (sender: SandboxEmailSender, firstTeamId: number, count: number): Promise<void[]> =>
    Promise.all(
        Array.from({ length: count }, (_, index) =>
            sender.captureBlocked(firstTeamId + index, false, 'recipient_not_member', 1)
        )
    )

describe('sandboxBlockedEventRedisConfig', () => {
    it('keeps the worker running when Redis refuses its connections', async () => {
        const { connection } = sandboxBlockedEventRedisConfig({
            url: '127.0.0.1',
            options: { port: 1, commandTimeout: 5000, retryStrategy: (attempt) => (attempt < 15 ? 5 : null) },
            name: 'sandbox-blocked-event-test',
        })

        await expect(createRedisFromConfig(connection)).rejects.toThrow()
        expect(killGracefully).not.toHaveBeenCalled()
    })

    it('sends no more store commands than the pool has clients while the store does not answer, and sends again once it answers', async () => {
        const store = await startStore({ answering: false })
        try {
            const sender = senderOn(
                store,
                jest.fn(() => Promise.resolve(null))
            )

            await blockProjects(sender, 1, MAX_OPEN_STORE_CALLS)
            await blockProjects(sender, 1, MAX_OPEN_STORE_CALLS)
            expect(store.setCommands()).toBe(MAX_OPEN_STORE_CALLS)

            store.answer()
            await blockProjects(sender, MAX_OPEN_STORE_CALLS + 1, MAX_OPEN_STORE_CALLS)
            expect(store.setCommands()).toBe(2 * MAX_OPEN_STORE_CALLS)
        } finally {
            store.stop()
        }
    }, 15_000)

    it('captures every event of a burst larger than the pool while the store answers', async () => {
        const store = await startStore({ answering: true })
        try {
            const getTeam = jest.fn((id: number) => Promise.resolve({ id }))
            const sender = senderOn(store, getTeam)

            await blockProjects(sender, 1, 2 * MAX_OPEN_STORE_CALLS)

            expect(store.setCommands()).toBe(2 * MAX_OPEN_STORE_CALLS)
            const capturedTeamIds = jest.mocked(captureTeamEvent).mock.calls.map(([team]) => team.id)
            expect(capturedTeamIds.sort((a, b) => a - b)).toEqual(
                Array.from({ length: 2 * MAX_OPEN_STORE_CALLS }, (_, index) => index + 1)
            )
        } finally {
            store.stop()
        }
    }, 15_000)
})
