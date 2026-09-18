import { EventEmitter } from 'events'

import { postgresClientErrorCounter } from './metrics'
import { PostgresRouter, PostgresUse } from './postgres'

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
