import { Pool, PoolClient, PoolConfig } from 'pg'
import { Counter, Gauge } from 'prom-client'

import { logger } from '~/common/utils/logger'

export type CyclotronPoolName = 'worker' | 'manager' | 'janitor' | 'subscription_matcher'

// pg sets `ending` on `end()`, but @types/pg does not declare it.
type TrackedPool = Pool & { readonly ending?: boolean }

const pgClientErrorsCounter = new Counter({
    name: 'cdp_cyclotron_v2_pg_client_errors_total',
    help: 'Errors from dropped connections to the cyclotron database, handled instead of crashing the process',
    labelNames: ['pool'],
})

const livePools = new Set<{ name: CyclotronPoolName; pool: TrackedPool }>()

function forgetEndedPools(): void {
    for (const entry of livePools) {
        if (entry.pool.ending) {
            livePools.delete(entry)
        }
    }
}

new Gauge({
    name: 'cdp_cyclotron_v2_pg_pool_clients',
    help: 'Clients of the cyclotron Postgres pools in this process, summed per pool name. state=waiting counts queries queued for a free client.',
    labelNames: ['pool', 'state'] as const,
    collect() {
        this.reset()
        forgetEndedPools()
        const totals = new Map<CyclotronPoolName, { total: number; idle: number; waiting: number }>()
        for (const entry of livePools) {
            const sum = totals.get(entry.name) ?? { total: 0, idle: 0, waiting: 0 }
            sum.total += entry.pool.totalCount
            sum.idle += entry.pool.idleCount
            sum.waiting += entry.pool.waitingCount
            totals.set(entry.name, sum)
        }
        for (const [pool, sum] of totals) {
            this.labels({ pool, state: 'total' }).set(sum.total)
            this.labels({ pool, state: 'idle' }).set(sum.idle)
            this.labels({ pool, state: 'waiting' }).set(sum.waiting)
        }
    },
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

    forgetEndedPools()
    livePools.add({ name, pool })
    return pool
}
