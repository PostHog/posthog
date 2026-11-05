import { DependencyUnavailableError } from '~/common/utils/db/error'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { PubSub } from '~/common/utils/pubsub'
import { TeamManager } from '~/common/utils/team-manager'

import { SandboxEmailSender } from '../messaging/sandbox-email-sender'
import { SandboxSenderStateService } from './sandbox-sender-state.service'

const pubSub = { on: jest.fn() } as unknown as PubSub

const idleClient = (): unknown => ({
    query: () => Promise.resolve({ rows: [] }),
    release: () => undefined,
    on: () => undefined,
    removeListener: () => undefined,
})

describe('SandboxSenderStateService', () => {
    const row = (status: string): unknown => ({ rows: [{ tenant_name: 'sandbox-tenant', sending_status: status }] })
    const transient = (): Error =>
        new DependencyUnavailableError('server closed the connection unexpectedly', 'Postgres', new Error())

    it.each([
        ['SES has the tenant enabled', [row('ENABLED')], 'open'],
        ['SES disabled the tenant', [row('DISABLED')], 'paused'],
        ['no state was synced yet', [{ rows: [] }], 'open'],
        ['a query fails once with a transient error', [transient(), row('DISABLED')], 'paused'],
        ['connecting fails once', ['refused', row('DISABLED')], 'paused'],
        [
            'the query fails with an error that a retry cannot fix',
            [new Error('relation does not exist')],
            'check_failed',
        ],
    ] as const)('answers the pause gate when %s', async (_case, outcomes, expected) => {
        for (const fresh of [false, true]) {
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
                    if (sql.startsWith('SET LOCAL')) {
                        return Promise.resolve({ rows: [] })
                    }
                    const outcome = queue.shift()
                    return outcome instanceof Error ? Promise.reject(outcome) : Promise.resolve(outcome)
                },
            } as unknown as PostgresRouter
            const sender = new SandboxEmailSender(
                {
                    enabled: true,
                    tenantName: 'sandbox-tenant',
                    configurationSetName: 'sandbox-email',
                    fromAddress: 'sender@example.com',
                    dailyTeamCap: '1',
                    dailyRecipientCap: '1',
                },
                {} as TeamManager,
                { useClient: jest.fn() },
                null,
                new SandboxSenderStateService(postgres, pubSub)
            )

            await expect(sender.pauseGate({ fresh })).resolves.toBe(expected)
        }
    })

    it.each([false, true])(
        'starts no lookup after the five second budget and fails the pause gate when the database stays unavailable (fresh: %s)',
        async (fresh) => {
            jest.useFakeTimers()
            jest.spyOn(Math, 'random').mockReturnValue(0)
            try {
                const lookupStarts: number[] = []
                const query = jest.fn((_tx: unknown, sql: string) => {
                    if (sql.startsWith('SET LOCAL')) {
                        return Promise.resolve({ rows: [] })
                    }
                    lookupStarts.push(performance.now())
                    return new Promise((_resolve, reject) => setTimeout(() => reject(transient()), 2_300))
                })
                const postgres = {
                    connect: () => Promise.resolve(idleClient()),
                    query,
                } as unknown as PostgresRouter
                const sender = new SandboxEmailSender(
                    {
                        enabled: true,
                        tenantName: 'sandbox-tenant',
                        configurationSetName: 'sandbox-email',
                        fromAddress: 'sender@example.com',
                        dailyTeamCap: '1',
                        dailyRecipientCap: '1',
                    },
                    {} as TeamManager,
                    { useClient: jest.fn() },
                    null,
                    new SandboxSenderStateService(postgres, pubSub)
                )

                const gate = sender.pauseGate({ fresh })
                await jest.advanceTimersByTimeAsync(10_000)
                await expect(gate).resolves.toBe('check_failed')
                const attempts = query.mock.calls.length
                await jest.advanceTimersByTimeAsync(30_000)
                expect(query.mock.calls).toHaveLength(attempts)
                expect(lookupStarts.map((at) => at - lookupStarts[0])).toEqual([0, 2_550])
            } finally {
                jest.restoreAllMocks()
                jest.useRealTimers()
            }
        }
    )

    it('reads the row again after a reload message, also when the message arrives during a cached or fresh lookup', async () => {
        let reload: (message: { tenantName: string }) => void = () => undefined
        const reloadingPubSub = {
            on: (_channel: string, handler: typeof reload) => {
                reload = handler
            },
        } as unknown as PubSub
        const storedStatuses = ['ENABLED', 'DISABLED', 'ENABLED', 'DISABLED', 'ENABLED', 'DISABLED']
        let holdNextLookup = false
        const heldLookups: (() => void)[] = []
        const query = jest.fn(async (_tx: unknown, sql: string) => {
            if (sql.startsWith('SET LOCAL')) {
                return { rows: [] }
            }
            const status = storedStatuses.shift()
            if (holdNextLookup) {
                holdNextLookup = false
                await new Promise<void>((resolve) => heldLookups.push(resolve))
            }
            return { rows: [{ tenant_name: 'sandbox-tenant', sending_status: status }] }
        })
        const lookups = (): number => query.mock.calls.filter(([, sql]) => !sql.startsWith('SET LOCAL')).length
        const service = new SandboxSenderStateService(
            { connect: () => Promise.resolve(idleClient()), query } as unknown as PostgresRouter,
            reloadingPubSub
        )

        await expect(service.isPaused('sandbox-tenant')).resolves.toBe(false)
        await expect(service.isPaused('sandbox-tenant')).resolves.toBe(false)
        expect(lookups()).toBe(1)

        reload({ tenantName: 'sandbox-tenant' })
        await expect(service.isPaused('sandbox-tenant')).resolves.toBe(true)
        expect(lookups()).toBe(2)

        const isPausedWithReloadDuringLookup = async (fresh: boolean): Promise<boolean> => {
            holdNextLookup = true
            const check = service.isPaused('sandbox-tenant', { fresh })
            while (heldLookups.length === 0) {
                await new Promise((resolve) => setImmediate(resolve))
            }
            reload({ tenantName: 'sandbox-tenant' })
            heldLookups.shift()!()
            return await check
        }

        reload({ tenantName: 'sandbox-tenant' })
        await expect(isPausedWithReloadDuringLookup(false)).resolves.toBe(true)
        expect(lookups()).toBe(4)

        await expect(isPausedWithReloadDuringLookup(true)).resolves.toBe(true)
        expect(lookups()).toBe(6)
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
