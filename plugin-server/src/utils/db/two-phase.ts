import { PoolClient } from 'pg'
import { PostgresRouter, PostgresUse, TransactionClient } from './postgres'
import { instrumentQuery } from '../metrics'
import { logger } from '../logger'
import { twoPhaseCommitFailuresCounter } from '~/worker/ingestion/persons/metrics'

// NICKS TODO: this will need at least two changes:
// 1. add a metric for the number of 2PCs that fail
// 2. add a env var that disables rollback of the primary if we don't make the second commit
// This'll allow us to test the code path without data being thrown away if something's wrong wit it

export type TwoPhaseSides = {
    left: { router: PostgresRouter; use: PostgresUse; name?: string }
    right: { router: PostgresRouter; use: PostgresUse; name?: string }
}

export class TwoPhaseCommitCoordinator {
    constructor(private sides: TwoPhaseSides) {}

    // NICKS TODO: we should decide what and how to set this GID
    private makeGid(tag: string): string {
        const ts = Date.now()
        const rand = Math.random().toString(36).slice(2, 10)

        // GID must <= 200 chars; terse and unique
        return `dualwrite:${tag}:${ts}:${rand}`

    }

    async rn<T>(
        tag: string,
        fn: (leftTx: TransactionClient, rightTx: TransactionClient) => Promise<T>
    ): Promise<T> {
        const gid = this.makeGid(tag)
        const {left, right} = this.sides

        return await instrumentQuery('query.dualwrite_spc', tag, async() => {
            let lClient: PoolClient | undefined
            let rClient: PoolClient | undefined
            let preparedLeft = false
            let preparedRight = false

            try {
                lClient = await left.router.connect(left.use)
                rClient = await right.router.connect(right.use)

                await lClient?.query('BEGIN')
                await rClient?.query('BEGIN')

                const result = await fn(
                    new TransactionClient(left.use, lClient),
                    new TransactionClient(right.use, rClient)
                )

                try {
                    await lClient?.query('PREPARE TRANSACTION $1', [gid])
                    preparedLeft = true
                } catch (e) {
                    twoPhaseCommitFailuresCounter.labels(tag, 'prepare_left_failed').inc()
                    throw e
                }
                try {
                    await rClient?.query('PREPARE TRANSACTION $1', [gid])
                    preparedRight = true
                } catch (e) {
                    twoPhaseCommitFailuresCounter.labels(tag, 'prepare_right_failed').inc()
                    throw e
                }

                lClient?.release()
                rClient?.release()
                lClient = undefined
                rClient = undefined

                try {
                    await left.router.query(left.use, 'COMMIT PREPARED $1', [gid], `2pc-commit-left:${tag}`)
                } catch (e) {
                    twoPhaseCommitFailuresCounter.labels(tag, 'commit_left_failed').inc()
                    throw e
                }
                try {
                    await right.router.query(right.use, 'COMMIT PREPARED $1', [gid], `2pc-commit-right:${tag}`)
                } catch (e) {
                    twoPhaseCommitFailuresCounter.labels(tag, 'commit_right_failed').inc()
                    throw e
                }

                return result
            } catch (error) {
                try{
                    if (preparedLeft) {
                        try {
                            await left.router.query(left.use, 'ROLLBACK PREPARED $1', [gid], `2pc-rollback-left:${tag}`)
                        } catch (e) {
                            twoPhaseCommitFailuresCounter.labels(tag, 'rollback_left_failed').inc()
                            throw e
                        }
                    } else if (lClient) {
                        await lClient.query('ROLLBACK')
                    }
                } catch (e) {
                    logger.error('Failed to rollback/cleanup left side of 2 PC')
                }
                try {
                    if (preparedRight) {
                        try {
                            await right.router.query(right.use, 'ROLLBACK PREPARED $1', [gid], `2pc-rollback-right:${tag}`)
                        } catch (e) {
                            twoPhaseCommitFailuresCounter.labels(tag, 'rollback_right_failed').inc()
                            throw e
                        }
                    } else if (rClient) {
                        await rClient.query('ROLLBACK')
                    }
                } catch (e) {
                    logger.error('Failed to rollback/cleanup right side of 2 PC')
                }
                logger.error('2 phase commit failed', {
                    tag,
                    gid,
                    left: this.sides.left.name ?? 'left',
                    right: this.sides.right.name ?? 'right',
                    error,
                })
                twoPhaseCommitFailuresCounter.labels(tag, 'run_failed').inc()
                throw error
            } finally {
                try {
                    lClient?.release()
                } catch {}
                try {
                    rClient?.release()
                } catch {}
            }
        })
    }
}

// NICKS TODO add tests for this