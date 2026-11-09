import { Pool, PoolClient, PoolConfig } from 'pg'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

export type CyclotronPoolName = 'worker' | 'manager' | 'janitor' | 'subscription_matcher'

const pgClientErrorsCounter = new Counter({
    name: 'cdp_cyclotron_v2_pg_client_errors_total',
    help: 'Errors from dropped connections to the cyclotron database, handled instead of crashing the process',
    labelNames: ['pool'],
})

function ignoreError(): void {}

export function createCyclotronPool(name: CyclotronPoolName, config: PoolConfig): Pool {
    const pool = new Pool(config)

    const reportDroppedClient = (error: Error): void => {
        pgClientErrorsCounter.labels({ pool: name }).inc()
        logger.warn('🔌', 'Cyclotron Postgres client dropped', { pool: name, error: String(error) })
    }

    pool.on('connect', (client: PoolClient) => client.once('error', reportDroppedClient).on('error', ignoreError))
    pool.on('error', ignoreError)

    return pool
}
