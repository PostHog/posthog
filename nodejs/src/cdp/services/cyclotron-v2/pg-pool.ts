import { Pool, PoolClient, PoolConfig } from 'pg'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

export type CyclotronPoolName = 'worker' | 'manager' | 'janitor' | 'subscription_matcher'

const pgClientErrorsCounter = new Counter({
    name: 'cdp_cyclotron_v2_pg_client_errors_total',
    help: 'Errors from dropped connections to the cyclotron database, handled instead of crashing the process',
    labelNames: ['pool'],
})

export function createCyclotronPool(name: CyclotronPoolName, config: PoolConfig): Pool {
    const pool = new Pool(config)
    const reported = new WeakSet<PoolClient>()

    const reportDroppedClient = (error: Error, client: PoolClient): void => {
        if (reported.has(client)) {
            return
        }
        reported.add(client)
        pgClientErrorsCounter.labels({ pool: name }).inc()
        logger.warn('🔌', 'Cyclotron Postgres client dropped', { pool: name, error: String(error) })
    }

    pool.on('connect', (client) => client.on('error', (error) => reportDroppedClient(error, client)))
    pool.on('error', reportDroppedClient)

    return pool
}
