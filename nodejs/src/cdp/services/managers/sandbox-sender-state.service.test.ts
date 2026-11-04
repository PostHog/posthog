import { DependencyUnavailableError } from '~/common/utils/db/error'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { PubSub } from '~/common/utils/pubsub'

import { SandboxSenderStateService } from './sandbox-sender-state.service'

const pubSub = { on: jest.fn() } as unknown as PubSub

const idleClient = (): unknown => ({
    query: () => Promise.resolve({ rows: [] }),
    release: () => undefined,
    on: () => undefined,
    removeListener: () => undefined,
})

describe('SandboxSenderStateService', () => {
    it('rides out a transient database error instead of failing the sandbox send', async () => {
        const select = jest
            .fn()
            .mockRejectedValueOnce(
                new DependencyUnavailableError('server closed the connection unexpectedly', 'Postgres', new Error())
            )
            .mockResolvedValueOnce({ rows: [{ tenant_name: 'sandbox-tenant', sending_status: 'DISABLED' }] })
        const service = new SandboxSenderStateService(
            {
                connect: () => Promise.resolve(idleClient()),
                query: (_tx: unknown, sql: string) =>
                    sql.startsWith('SET LOCAL') ? Promise.resolve({ rows: [] }) : select(),
            } as unknown as PostgresRouter,
            pubSub
        )

        await expect(service.isPaused('sandbox-tenant')).resolves.toBe(true)
    })

    it('fails fresh checks at their deadline while the pool has no connection, keeps at most five lookups open, and runs no query for them later', async () => {
        jest.useFakeTimers()
        try {
            const waitingForConnection: (() => void)[] = []
            const query = jest.fn((_target: unknown, sql: string) =>
                Promise.resolve({
                    rows: sql.startsWith('SET LOCAL')
                        ? []
                        : [{ tenant_name: 'sandbox-tenant', sending_status: 'ENABLED' }],
                })
            )
            const pool = {
                connect: () => new Promise((resolve) => waitingForConnection.push(() => resolve(idleClient()))),
                query,
            } as unknown as PostgresRouter
            const service = new SandboxSenderStateService(pool, pubSub)

            const outcomes = Promise.allSettled(
                Array.from({ length: 20 }, () => service.isPaused('sandbox-tenant', { fresh: true }))
            )
            await jest.advanceTimersByTimeAsync(3_000)

            expect((await outcomes).map((outcome) => outcome.status)).toEqual(Array(20).fill('rejected'))
            expect(waitingForConnection).toHaveLength(5)
            waitingForConnection.forEach((connect) => connect())
            await jest.advanceTimersByTimeAsync(0)
            expect(query).not.toHaveBeenCalled()
        } finally {
            jest.useRealTimers()
        }
    })
})
