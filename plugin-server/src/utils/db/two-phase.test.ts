import { twoPhaseCommitFailuresCounter } from '~/worker/ingestion/persons/metrics'

import { PostgresUse } from './postgres'
import { TwoPhaseCommitCoordinator } from './two-phase'

type QueryCall = { sql: string; args?: any[] }

class FakePoolClient {
    public calls: QueryCall[] = []
    constructor(private opts: { failOnPrepare?: boolean; side: 'left' | 'right' }) {}

    query(sql: string, args?: any[]): any {
        this.calls.push({ sql, args })
        if (sql.startsWith('PREPARE TRANSACTION') && this.opts.failOnPrepare) {
            return Promise.reject(new Error(`prepare_failed_${this.opts.side}`))
        }
        // BEGIN / ROLLBACK are always ok in this fake
        return Promise.resolve({ rowCount: 0, rows: [] })
    }

    release(): void {
        // no-op
    }
}

class FakeRouter {
    public client: FakePoolClient
    public routerCalls: QueryCall[] = []
    constructor(
        private side: 'left' | 'right',
        private opts: { failOnPrepare?: boolean; failCommitPrepared?: boolean; failRollbackPrepared?: boolean } = {}
    ) {
        this.client = new FakePoolClient({ failOnPrepare: opts.failOnPrepare, side })
    }

    connect(_use: PostgresUse): FakePoolClient {
        return this.client
    }

    query(_use: PostgresUse, sql: string, args?: any[], _tag?: string): any {
        this.routerCalls.push({ sql, args })
        if (sql.startsWith('COMMIT PREPARED') && this.opts.failCommitPrepared) {
            return Promise.reject(new Error(`commit_failed_${this.side}`))
        }
        if (sql.startsWith('ROLLBACK PREPARED') && this.opts.failRollbackPrepared) {
            return Promise.reject(new Error(`rollback_failed_${this.side}`))
        }
        return Promise.resolve({ rowCount: 0, rows: [] })
    }
}

// Helper to capture metric label+inc pairs
function spyOn2pcFailures() {
    const labelsSpy = jest.spyOn(twoPhaseCommitFailuresCounter, 'labels') as any
    const calls: Array<{ tag: string; phase: string }> = []
    labelsSpy.mockImplementation((tag: string, phase: string) => {
        return { inc: jest.fn(() => calls.push({ tag, phase })) }
    })
    return { labelsSpy, calls }
}

describe('TwoPhaseCommitCoordinator', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    test('success path commits both sides', async () => {
        const left = new FakeRouter('left')
        const right = new FakeRouter('right')
        const coord = new TwoPhaseCommitCoordinator({
            left: { router: left as any, use: PostgresUse.PERSONS_WRITE, name: 'L' },
            right: { router: right as any, use: PostgresUse.PERSONS_WRITE, name: 'R' },
        })

        const { labelsSpy, calls } = spyOn2pcFailures()

        const result = await coord.run('ok', () => Promise.resolve('done'))

        expect(result).toBe('done')
        // Both sides prepared via client
        expect(left.client.calls.find((c) => c.sql.startsWith('PREPARE TRANSACTION'))).toBeTruthy()
        expect(right.client.calls.find((c) => c.sql.startsWith('PREPARE TRANSACTION'))).toBeTruthy()
        // Both sides committed via router
        expect(left.routerCalls.find((c) => c.sql.startsWith('COMMIT PREPARED'))).toBeTruthy()
        expect(right.routerCalls.find((c) => c.sql.startsWith('COMMIT PREPARED'))).toBeTruthy()
        // No failure metrics
        expect(labelsSpy).not.toHaveBeenCalled()
        expect(calls.length).toBe(0)
    })

    test('prepare left fails increments prepare_left_failed and run_failed', async () => {
        const left = new FakeRouter('left', { failOnPrepare: true })
        const right = new FakeRouter('right')
        const coord = new TwoPhaseCommitCoordinator({
            left: { router: left as any, use: PostgresUse.PERSONS_WRITE },
            right: { router: right as any, use: PostgresUse.PERSONS_WRITE },
        })

        const { calls } = spyOn2pcFailures()

        await expect(coord.run('t1', () => Promise.resolve('x'))).rejects.toThrow(/prepare_failed_left/)

        const phases = calls.map((c) => c.phase)
        expect(phases).toContain('prepare_left_failed')
        expect(phases).toContain('run_failed')
        // Right side's prepare succeeded, so it should be rolled back via router
        expect(right.routerCalls.find((c) => c.sql.startsWith('ROLLBACK PREPARED'))).toBeTruthy()
    })

    test('prepare right fails increments prepare_right_failed and run_failed and rolls back left prepared', async () => {
        const left = new FakeRouter('left')
        const right = new FakeRouter('right', { failOnPrepare: true })
        const coord = new TwoPhaseCommitCoordinator({
            left: { router: left as any, use: PostgresUse.PERSONS_WRITE },
            right: { router: right as any, use: PostgresUse.PERSONS_WRITE },
        })

        const { calls } = spyOn2pcFailures()

        await expect(coord.run('t2', () => Promise.resolve('x'))).rejects.toThrow(/prepare_failed_right/)

        const phases = calls.map((c) => c.phase)
        expect(phases).toContain('prepare_right_failed')
        expect(phases).toContain('run_failed')
        // Left was prepared and should have been rolled back via router
        expect(left.routerCalls.find((c) => c.sql.startsWith('ROLLBACK PREPARED'))).toBeTruthy()
    })

    test('commit left fails increments commit_left_failed and run_failed', async () => {
        const left = new FakeRouter('left', { failCommitPrepared: true })
        const right = new FakeRouter('right')
        const coord = new TwoPhaseCommitCoordinator({
            left: { router: left as any, use: PostgresUse.PERSONS_WRITE },
            right: { router: right as any, use: PostgresUse.PERSONS_WRITE },
        })

        const { calls } = spyOn2pcFailures()

        await expect(coord.run('t3', () => Promise.resolve('x'))).rejects.toThrow(/commit_failed_left/)

        const phases = calls.map((c) => c.phase)
        expect(phases).toContain('commit_left_failed')
        expect(phases).toContain('run_failed')
        // After failure, we attempt rollbacks
        expect(left.routerCalls.find((c) => c.sql.startsWith('ROLLBACK PREPARED'))).toBeTruthy()
        expect(right.routerCalls.find((c) => c.sql.startsWith('ROLLBACK PREPARED'))).toBeTruthy()
    })

    test('commit right fails increments commit_right_failed and run_failed', async () => {
        const left = new FakeRouter('left')
        const right = new FakeRouter('right', { failCommitPrepared: true })
        const coord = new TwoPhaseCommitCoordinator({
            left: { router: left as any, use: PostgresUse.PERSONS_WRITE },
            right: { router: right as any, use: PostgresUse.PERSONS_WRITE },
        })

        const { calls } = spyOn2pcFailures()

        await expect(coord.run('t4', () => Promise.resolve('x'))).rejects.toThrow(/commit_failed_right/)

        const phases = calls.map((c) => c.phase)
        expect(phases).toContain('commit_right_failed')
        expect(phases).toContain('run_failed')
        // Left side was already committed when right failed, so it should NOT attempt rollback
        // (you cannot rollback an already-committed transaction)
        expect(left.routerCalls.find((c) => c.sql.startsWith('ROLLBACK PREPARED'))).toBeFalsy()
        // Right side's prepared transaction should be rolled back
        expect(right.routerCalls.find((c) => c.sql.startsWith('ROLLBACK PREPARED'))).toBeTruthy()
    })

    test('fn throws increments run_failed and rolls back both local txs', async () => {
        const left = new FakeRouter('left')
        const right = new FakeRouter('right')
        const coord = new TwoPhaseCommitCoordinator({
            left: { router: left as any, use: PostgresUse.PERSONS_WRITE },
            right: { router: right as any, use: PostgresUse.PERSONS_WRITE },
        })

        const { calls } = spyOn2pcFailures()

        await expect(
            coord.run('t5', () => {
                throw new Error('boom')
            })
        ).rejects.toThrow('boom')

        const phases = calls.map((c) => c.phase)
        expect(phases).toContain('run_failed')
        // Both sides should have rolled back local txs (not prepared)
        expect(left.client.calls.find((c) => c.sql === 'ROLLBACK')).toBeTruthy()
        expect(right.client.calls.find((c) => c.sql === 'ROLLBACK')).toBeTruthy()
    })
})
