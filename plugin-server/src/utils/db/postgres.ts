// Postgres

import { StatsD } from 'hot-shots'
import { Client, Pool, PoolClient, QueryConfig, QueryResult, QueryResultRow } from 'pg'

import { PluginsServerConfig } from '../../types'
import { instrumentQuery } from '../../utils/metrics'
import { status } from '../status'
import { createPostgresPool } from '../utils'
import { POSTGRES_UNAVAILABLE_ERROR_MESSAGES } from './db'
import { DependencyUnavailableError } from './error'
import { timeoutGuard } from './utils'

export enum PostgresUse {
    COMMON, // Main PG master with common tables, we need to move as many queries away from it as possible
    COMMON_READ, // Read replica on the common tables, uses need to account for possible replication delay
    PLUGIN_STORAGE, // Plugin Storage table, no read replica for it
}

export class PostgresRouter {
    pools: Map<PostgresUse, Pool>
    statsd: StatsD | undefined

    constructor(serverConfig: PluginsServerConfig, statsd: StatsD | undefined) {
        status.info('🤔', `Connecting to common Postgresql...`)
        const commonClient = createPostgresPool(serverConfig.DATABASE_URL)
        status.info('👍', `Common Postgresql ready`)
        // We fill the pools maps with the default client by default as a safe fallback for hobby,
        // the rest of the constructor overrides entries if more database URLs are passed.
        this.pools = new Map([
            [PostgresUse.COMMON, commonClient],
            [PostgresUse.COMMON_READ, commonClient],
            [PostgresUse.PLUGIN_STORAGE, commonClient],
        ])
        this.statsd = statsd

        if (serverConfig.DATABASE_READONLY_URL) {
            status.info('🤔', `Connecting to read-only common Postgresql...`)
            this.pools.set(PostgresUse.COMMON_READ, createPostgresPool(serverConfig.DATABASE_READONLY_URL))
            status.info('👍', `Read-only common Postgresql ready`)
        }
        if (serverConfig.PLUGIN_STORAGE_DATABASE_URL) {
            status.info('🤔', `Connecting to plugin-storage Postgresql...`)
            this.pools.set(PostgresUse.PLUGIN_STORAGE, createPostgresPool(serverConfig.PLUGIN_STORAGE_DATABASE_URL))
            status.info('👍', `Plugin-storage Postgresql ready`)
        }
    }

    public query<R extends QueryResultRow = any, I extends any[] = any[]>(
        usage: PostgresUse,
        queryString: string | QueryConfig<I>,
        values: I | undefined,
        tag: string
    ): Promise<QueryResult<R>> {
        const wrappedTag = `${PostgresUse[usage]}<${tag}>`
        return postgresQuery(this.pools.get(usage)!, queryString, values, wrappedTag, this.statsd)
    }

    public async bulkInsert<T extends Array<any>>(
        usage: PostgresUse,
        // Should have {VALUES} as a placeholder
        queryWithPlaceholder: string,
        values: Array<T>,
        tag: string
    ): Promise<void> {
        if (values.length === 0) {
            return
        }

        const valuesWithPlaceholders = values
            .map((array, index) => {
                const len = array.length
                const valuesWithIndexes = array.map((_, subIndex) => `$${index * len + subIndex + 1}`)
                return `(${valuesWithIndexes.join(', ')})`
            })
            .join(', ')

        await this.query(usage, queryWithPlaceholder.replace('{VALUES}', valuesWithPlaceholders), values.flat(), tag)
    }

    public transaction<ReturnType>(
        usage: PostgresUse,
        tag: string,
        transaction: (client: PoolClient) => Promise<ReturnType>
    ): Promise<ReturnType> {
        const wrappedTag = `${PostgresUse[usage]}<${tag}>`
        return instrumentQuery(this.statsd, 'query.postgres_transation', wrappedTag, async () => {
            const timeout = timeoutGuard(`Postgres slow transaction warning after 30 sec!`)
            const client = await this.pools.get(usage)!.connect()
            try {
                await client.query('BEGIN')
                const response = await transaction(client)
                await client.query('COMMIT')
                return response
            } catch (e) {
                await client.query('ROLLBACK')

                // if Postgres is down the ROLLBACK above won't work, but the transaction shouldn't be committed either
                if (e.message && POSTGRES_UNAVAILABLE_ERROR_MESSAGES.some((message) => e.message.includes(message))) {
                    throw new DependencyUnavailableError(e.message, 'Postgres', e)
                }

                throw e
            } finally {
                client.release()
                clearTimeout(timeout)
            }
        })
    }

    async end() {
        // Close all the connection pools
        const uniquePools: Set<Pool> = new Set(this.pools.values())
        for (const pool of uniquePools) {
            await pool.end()
        }
    }
}

function postgresQuery<R extends QueryResultRow = any, I extends any[] = any[]>(
    // Un-exported, use PostgresRouter to run PG queries
    client: Client | Pool | PoolClient,
    queryString: string | QueryConfig<I>,
    values: I | undefined,
    tag: string,
    statsd?: StatsD
): Promise<QueryResult<R>> {
    return instrumentQuery(statsd, 'query.postgres', tag, async () => {
        const queryConfig =
            typeof queryString === 'string'
                ? {
                      // Annotate query string to give context when looking at DB logs
                      text: `/* plugin-server:${tag} */ ${queryString}`,
                      values,
                  }
                : queryString

        try {
            return await client.query(queryConfig, values)
        } catch (error) {
            if (
                error.message &&
                POSTGRES_UNAVAILABLE_ERROR_MESSAGES.some((message) => error.message.includes(message))
            ) {
                throw new DependencyUnavailableError(error.message, 'Postgres', error)
            }
            throw error
        }
    })
}

export async function assertTablesExist(client: Client | Pool | PoolClient, tables: string[]): Promise<void> {
    // Allows to check at startup that the configured PG holds the expected tables,
    // to catch misconfigurations before the entire deployment rolls out.
    const found: string[] = (
        await postgresQuery(
            client,
            'SELECT relname FROM pg_class WHERE relname = ANY($1) ORDER BY relname;',
            [tables],
            'assertTablesExist'
        )
    ).rows.map((row) => row.relname)

    const missing = tables.filter((table) => !found.includes(table))
    if (missing.length > 0) {
        throw new Error(`Configured PG target does not hold the expected tables: ${missing.join(', ')}`)
    }
    return Promise.resolve()
}
