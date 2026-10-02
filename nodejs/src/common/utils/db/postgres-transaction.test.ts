import { EventEmitter } from 'events'

import { postgresClientErrorCounter, postgresOpenTransactionsGauge } from './metrics'
import { PostgresRouter, PostgresUse } from './postgres'

async function metricValue(metric: { get: () => Promise<any> }, labels: Record<string, string>): Promise<number> {
    const values = (await metric.get()).values as { labels: Record<string, string>; value: number }[]
    const match = values.find((sample) => Object.entries(labels).every(([key, value]) => sample.labels[key] === value))
    return match?.value ?? 0
}

type FakeClient = EventEmitter & { query: jest.Mock; release: jest.Mock }

describe('postgres transaction client failures', () => {
    let client: FakeClient
    let router: PostgresRouter

    beforeEach(() => {
        client = Object.assign(new EventEmitter(), {
            query: jest.fn().mockResolvedValue({ rows: [] }),
            release: jest.fn(),
        }) as FakeClient

        router = new PostgresRouter({ DATABASE_URL: 'postgres://fake', POSTGRES_CONNECTION_POOL_SIZE: 1 })
        // pg pools connect lazily, so the real ones built by the constructor never dial.
        ;(router as any).pools = new Map([[PostgresUse.COMMON_WRITE, { connect: jest.fn().mockResolvedValue(client) }]])
    })

    it('counts a client lost mid-transaction and has the pool destroy it', async () => {
        const lost = new Error('Connection terminated unexpectedly')
        const errors = (): Promise<number> => metricValue(postgresClientErrorCounter, { pool: 'COMMON_WRITE' })
        const before = await errors()

        await expect(
            router.transaction(PostgresUse.COMMON_WRITE, 'merge', () => {
                client.emit('error', lost)
                return Promise.reject(new Error('query failed'))
            })
        ).rejects.toThrow('query failed')

        expect(client.release).toHaveBeenCalledWith(lost)
        expect(await errors()).toBe(before + 1)
        expect(client.listenerCount('error')).toBe(0)
    })

    it('keeps the original error when ROLLBACK fails, and has the pool destroy the client', async () => {
        const rollbackFailure = new Error('Connection terminated unexpectedly')
        client.query.mockImplementation((sql: string) =>
            sql === 'ROLLBACK' ? Promise.reject(rollbackFailure) : Promise.resolve({ rows: [] })
        )

        await expect(
            router.transaction(PostgresUse.COMMON_WRITE, 'merge', () =>
                Promise.reject(new Error('fold target was deleted concurrently'))
            )
        ).rejects.toThrow('fold target was deleted concurrently')

        expect(client.release).toHaveBeenCalledWith(rollbackFailure)
    })

    it.each([
        ['commits', () => Promise.resolve()],
        ['throws', () => Promise.reject(new Error('query failed'))],
    ])('reports a transaction as open only until it %s', async (outcome, finish) => {
        const tag = `gauge-${outcome}`
        const open = (): Promise<number> => metricValue(postgresOpenTransactionsGauge, { tag })

        let during = -1
        await router
            .transaction(PostgresUse.COMMON_WRITE, tag, async () => {
                during = await open()
                return finish()
            })
            .catch(() => undefined)

        expect(during).toBe(1)
        expect(await open()).toBe(0)
    })
})
