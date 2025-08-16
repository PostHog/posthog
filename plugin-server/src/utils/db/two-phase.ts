import { PoolClient } from 'pg'

import { twoPhaseCommitFailuresCounter } from '~/worker/ingestion/persons/metrics'

import { logger } from '../logger'
import { instrumentQuery } from '../metrics'
import { PostgresRouter, PostgresUse, TransactionClient } from './postgres'

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

    private makeGid(tag: string): string {
        const ts = Date.now()
        const rand = Math.random().toString(36).slice(2, 10)

        // GID must <= 200 chars; terse and unique
        return `dualwrite:${tag}:${ts}:${rand}`
    }

    async run<T>(tag: string, fn: (leftTx: TransactionClient, rightTx: TransactionClient) => Promise<T>): Promise<T> {
        // GID is unique across DBs but has as shared root
        // this is so that the global id supports running 2PCs across two databases
        // on the same cluster/machine
        // the transaction id would clash if we used the exact same id
        const gidRoot = this.makeGid(tag)
        const gidLeft = `${gidRoot}:left`
        const gidRight = `${gidRoot}:right`
        const gidLeftLiteral = `'${gidLeft.replace(/'/g, "''")}'`
        const gidRightLiteral = `'${gidRight.replace(/'/g, "''")}'`
        const { left, right } = this.sides

        return await instrumentQuery('query.dualwrite_spc', tag, async () => {
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
                    await lClient?.query(`PREPARE TRANSACTION ${gidLeftLiteral}`)
                    preparedLeft = true
                } catch (e) {
                    twoPhaseCommitFailuresCounter.labels(tag, 'prepare_left_failed').inc()
                    throw e
                }
                try {
                    await rClient?.query(`PREPARE TRANSACTION ${gidRightLiteral}`)
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
                    await left.router.query(left.use, `COMMIT PREPARED ${gidLeftLiteral}`, [], `2pc-commit-left:${tag}`)
                } catch (e) {
                    twoPhaseCommitFailuresCounter.labels(tag, 'commit_left_failed').inc()
                    throw e
                }
                try {
                    await right.router.query(
                        right.use,
                        `COMMIT PREPARED ${gidRightLiteral}`,
                        [],
                        `2pc-commit-right:${tag}`
                    )
                } catch (e) {
                    twoPhaseCommitFailuresCounter.labels(tag, 'commit_right_failed').inc()
                    throw e
                }

                return result
            } catch (error) {
                try {
                    if (preparedLeft) {
                        try {
                            await left.router.query(
                                left.use,
                                `ROLLBACK PREPARED ${gidLeftLiteral}`,
                                [],
                                `2pc-rollback-left:${tag}`
                            )
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
                            await right.router.query(
                                right.use,
                                `ROLLBACK PREPARED ${gidRightLiteral}`,
                                [],
                                `2pc-rollback-right:${tag}`
                            )
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
                    gid: gidRoot,
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
