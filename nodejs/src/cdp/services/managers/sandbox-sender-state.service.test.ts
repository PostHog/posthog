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

const isLookup = (sql: string): boolean => !sql.startsWith('SET LOCAL')

describe('SandboxSenderStateService', () => {
    const row = (paused: boolean): unknown => ({ rows: [{ paused }] })
    const transient = (): Error =>
        new DependencyUnavailableError('server closed the connection unexpectedly', 'Postgres', new Error())

    it.each([
        ['SES has the tenant enabled', [row(false)], false],
        ['SES disabled the tenant', [row(true)], true],
        ['no state was synced yet', [{ rows: [] }], false],
        ['a query fails once with a transient error', [transient(), row(true)], true],
        ['connecting fails once', ['refused', row(true)], true],
        ['the query fails with an error that a retry cannot fix', [new Error('relation does not exist')], 'rejects'],
    ] as const)('answers when %s', async (_case, outcomes, expected) => {
        const queue: unknown[] = [...outcomes]
        const postgres = {
            connect: () => {
                if (queue[0] === 'refused') {
                    queue.shift()
                    return Promise.reject(new Error('connect ECONNREFUSED 127.0.0.1:6432'))
                }
                return Promise.resolve(idleClient())
            },
            query: (_tx: unknown, sql: string) => {
                if (!isLookup(sql)) {
                    return Promise.resolve({ rows: [] })
                }
                const outcome = queue.shift()
                return outcome instanceof Error ? Promise.reject(outcome) : Promise.resolve(outcome)
            },
        } as unknown as PostgresRouter
        const check = new SandboxSenderStateService(postgres, 'sandbox-tenant', pubSub).isPaused()

        if (expected === 'rejects') {
            await expect(check).rejects.toThrow('relation does not exist')
        } else {
            await expect(check).resolves.toBe(expected)
        }
    })

    it('fails within the five second budget when the database stays unavailable, without a last attempt that cannot finish', async () => {
        jest.useFakeTimers()
        jest.spyOn(Math, 'random').mockReturnValue(0)
        try {
            const lookupStarts: number[] = []
            const query = jest.fn((_tx: unknown, sql: string) => {
                if (!isLookup(sql)) {
                    return Promise.resolve({ rows: [] })
                }
                lookupStarts.push(performance.now())
                return new Promise((_resolve, reject) => setTimeout(() => reject(transient()), 2_200))
            })
            const service = new SandboxSenderStateService(
                { connect: () => Promise.resolve(idleClient()), query } as unknown as PostgresRouter,
                'sandbox-tenant',
                pubSub
            )

            let settledAt: number | undefined
            const check = service.isPaused({ fresh: true })
            void check.catch(() => (settledAt = performance.now()))
            await jest.advanceTimersByTimeAsync(10_000)
            await expect(check).rejects.toThrow('server closed the connection unexpectedly')
            expect(settledAt! - lookupStarts[0]).toBeLessThanOrEqual(5_000)
            expect(lookupStarts.length).toBeGreaterThan(1)
            expect(Math.max(...lookupStarts) - lookupStarts[0]).toBeLessThanOrEqual(5_000 - 250)
            const attempts = query.mock.calls.length
            await jest.advanceTimersByTimeAsync(30_000)
            expect(query.mock.calls).toHaveLength(attempts)
        } finally {
            jest.restoreAllMocks()
            jest.useRealTimers()
        }
    })

    it('reads again after a reload message and after a fresh read, and never caches a read that started before the message', async () => {
        let reload: (message: { tenantName: string }) => void = () => undefined
        const reloadingPubSub = {
            on: (_channel: string, handler: typeof reload) => {
                reload = handler
            },
        } as unknown as PubSub
        const storedPaused = [false, true, false, true, false]
        let holdNextLookup = false
        const heldLookups: (() => void)[] = []
        const query = jest.fn(async (_tx: unknown, sql: string) => {
            if (!isLookup(sql)) {
                return { rows: [] }
            }
            const paused = storedPaused.shift()
            if (holdNextLookup) {
                holdNextLookup = false
                await new Promise<void>((resolve) => heldLookups.push(resolve))
            }
            return { rows: [{ paused }] }
        })
        const lookups = (): number => query.mock.calls.filter(([, sql]) => isLookup(sql)).length
        const service = new SandboxSenderStateService(
            { connect: () => Promise.resolve(idleClient()), query } as unknown as PostgresRouter,
            'sandbox-tenant',
            reloadingPubSub
        )

        await expect(service.isPaused()).resolves.toBe(false)
        await expect(service.isPaused()).resolves.toBe(false)
        expect(lookups()).toBe(1)

        reload({ tenantName: 'sandbox-tenant' })
        await expect(service.isPaused()).resolves.toBe(true)
        expect(lookups()).toBe(2)

        await expect(service.isPaused({ fresh: true })).resolves.toBe(false)
        await expect(service.isPaused()).resolves.toBe(false)
        expect(lookups()).toBe(3)

        holdNextLookup = true
        const startedBeforeMessage = service.isPaused({ fresh: true })
        while (heldLookups.length === 0) {
            await new Promise((resolve) => setImmediate(resolve))
        }
        reload({ tenantName: 'sandbox-tenant' })
        await expect(service.isPaused()).resolves.toBe(false)
        heldLookups.shift()!()
        await expect(startedBeforeMessage).resolves.toBe(true)
        await expect(service.isPaused()).resolves.toBe(false)
        expect(lookups()).toBe(5)
    })

    it('fails fresh checks at their deadline while the pool has no connection, keeps at most five lookups open, and runs no query for them later', async () => {
        jest.useFakeTimers()
        try {
            const waitingForConnection: (() => void)[] = []
            const query = jest.fn(() => Promise.resolve({ rows: [{ paused: false }] }))
            const pool = {
                connect: () => new Promise((resolve) => waitingForConnection.push(() => resolve(idleClient()))),
                query,
            } as unknown as PostgresRouter
            const service = new SandboxSenderStateService(pool, 'sandbox-tenant', pubSub)

            const outcomes = Promise.allSettled(Array.from({ length: 20 }, () => service.isPaused({ fresh: true })))
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
