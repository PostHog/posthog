import { EventEmitter } from 'events'

import {
    postgresClientErrorCounter,
    postgresClientRemovedInUseCounter,
    postgresOpenAtShutdownCounter,
    postgresOpenTransactionsGauge,
} from './metrics'
import { PostgresRouter, PostgresUse, instrumentPool } from './postgres'

async function metricValue(metric: { get: () => Promise<any> }, labels: Record<string, string>): Promise<number> {
    const values = (await metric.get()).values as { labels: Record<string, string>; value: number }[]
    const match = values.find((sample) => Object.entries(labels).every(([key, value]) => sample.labels[key] === value))
    return match?.value ?? 0
}

type FakeClient = EventEmitter & { query: jest.Mock; release: jest.Mock }

describe('postgres transaction client failures', () => {
    let client: FakeClient
    let pool: EventEmitter & { connect: jest.Mock; end: jest.Mock }
    let router: PostgresRouter

    beforeEach(() => {
        client = Object.assign(new EventEmitter(), {
            query: jest.fn().mockResolvedValue({ rows: [] }),
            release: jest.fn(),
        }) as FakeClient

        pool = Object.assign(new EventEmitter(), {
            connect: jest.fn().mockResolvedValue(client),
            end: jest.fn(),
        })
        instrumentPool(pool as any, 'COMMON_WRITE')

        router = new PostgresRouter({ DATABASE_URL: 'postgres://fake', POSTGRES_CONNECTION_POOL_SIZE: 1 })
        // pg pools connect lazily, so the real ones built by the constructor never dial.
        ;(router as any).pools = new Map([[PostgresUse.COMMON_WRITE, pool]])
    })

    it('flags a client the pool removed while a transaction was using it', async () => {
        const removedInUse = (): Promise<number> =>
            metricValue(postgresClientRemovedInUseCounter, { tag: 'removeRace' })
        const before = await removedInUse()

        await router.transaction(PostgresUse.COMMON_WRITE, 'removeRace', async (tx) => {
            await router.query(tx, 'SELECT 1', undefined, 'claimLifecycleOp')
            pool.emit('remove', client)
        })

        expect(await removedInUse()).toBe(before + 1)
    })

    it('does not flag a client the pool removes after its transaction finished', async () => {
        const removedInUse = (): Promise<number> =>
            metricValue(postgresClientRemovedInUseCounter, { tag: 'cleanRelease' })
        const before = await removedInUse()

        await router.transaction(PostgresUse.COMMON_WRITE, 'cleanRelease', () => Promise.resolve())
        pool.emit('remove', client)

        expect(await removedInUse()).toBe(before)
    })

    it('reports a transaction as open only while it is running', async () => {
        const open = (): Promise<number> => metricValue(postgresOpenTransactionsGauge, { tag: 'gaugeCheck' })

        let during = -1
        await router.transaction(PostgresUse.COMMON_WRITE, 'gaugeCheck', async () => {
            during = await open()
        })

        expect(during).toBe(1)
        expect(await open()).toBe(0)
    })

    it('names a transaction that is still open when the pools close', async () => {
        let reached: () => void = () => {}
        let finish: () => void = () => {}
        const entered = new Promise<void>((resolve) => (reached = resolve))

        const running = router.transaction(PostgresUse.COMMON_WRITE, 'mergePeopleFold', async (tx) => {
            await router.query(tx, 'DELETE FROM lifecycle_op', undefined, 'releaseLifecycleMarks')
            reached()
            await new Promise<void>((resolve) => (finish = resolve))
        })
        await entered

        await router.end()

        expect(await metricValue(postgresOpenAtShutdownCounter, { tag: 'mergePeopleFold' })).toBeGreaterThan(0)

        finish()
        await running
    })

    it('releases a client that errored so the pool destroys it instead of reusing it', async () => {
        const lost = new Error('Connection terminated unexpectedly')

        await expect(
            router.transaction(PostgresUse.COMMON_WRITE, 'merge', () => {
                client.emit('error', lost)
                return Promise.reject(new Error('query failed'))
            })
        ).rejects.toThrow()

        expect(client.release).toHaveBeenCalledWith(lost)
    })

    it('keeps the original error when ROLLBACK cannot run on a dead connection', async () => {
        client.query.mockImplementation((sql: string) =>
            sql === 'ROLLBACK'
                ? Promise.reject(new Error('Connection terminated unexpectedly'))
                : Promise.resolve({ rows: [] })
        )

        await expect(
            router.transaction(PostgresUse.COMMON_WRITE, 'merge', () =>
                Promise.reject(new Error('fold target was deleted concurrently'))
            )
        ).rejects.toThrow('fold target was deleted concurrently')
    })

    it('attributes a lost connection to the statement that was in flight', async () => {
        let failQuery: () => void = () => {}
        client.query.mockImplementation((config: any) =>
            typeof config === 'object' && String(config.text).includes('claimLifecycleOp')
                ? new Promise((_, reject) => {
                      failQuery = () => reject(new Error('Connection terminated unexpectedly'))
                  })
                : Promise.resolve({ rows: [] })
        )

        await expect(
            router.transaction(PostgresUse.COMMON_WRITE, 'merge', async (tx) => {
                const pending = router.query(tx, 'INSERT INTO lifecycle_op', undefined, 'claimLifecycleOp')
                client.emit('error', new Error('Connection terminated unexpectedly'))
                failQuery()
                await pending
            })
        ).rejects.toThrow()

        const sample = (await postgresClientErrorCounter.get()).values.find(
            (value) => value.labels.in_flight === 'claimLifecycleOp'
        )
        expect(sample?.value).toBeGreaterThan(0)
    })
})
