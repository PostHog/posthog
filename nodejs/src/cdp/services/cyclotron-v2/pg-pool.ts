import { Pool, PoolClient, PoolConfig } from 'pg'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

export type CyclotronPoolName = 'worker' | 'manager' | 'janitor' | 'subscription_matcher'

const pgClientErrorsCounter = new Counter({
    name: 'cdp_cyclotron_v2_pg_client_errors_total',
    help: 'Errors from dropped connections to the cyclotron database, handled instead of crashing the process',
    labelNames: ['pool'],
})

// An `error` event with no listener throws, and an uncaught exception stops the server.
// pg emits one on the client when its connection drops, idle or checked out, and the pool
// re-emits it for an idle client after discarding that client.
export function createCyclotronPool(name: CyclotronPoolName, config: PoolConfig): Pool {
    const pool = new Pool(config)

    const onError = (error: Error): void => {
        pgClientErrorsCounter.labels({ pool: name }).inc()
        logger.warn('🔌', 'Cyclotron Postgres client dropped', { pool: name, error: String(error) })
    }

    pool.on('connect', (client: PoolClient) => client.on('error', onError))
    // The client listener above already counted it; this only stops the pool's re-emit from throwing.
    pool.on('error', () => {})

    return pool
}
