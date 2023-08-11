// Postgres

import { StatsD } from 'hot-shots'
import { Client, Pool, PoolClient, QueryConfig, QueryResult, QueryResultRow } from 'pg'

import { PluginsServerConfig } from '../../types'
import { instrumentQuery } from '../../utils/metrics'
import { status } from '../status'
import { createPostgresPool } from '../utils'
import { POSTGRES_UNAVAILABLE_ERROR_MESSAGES } from './db'
import { DependencyUnavailableError } from './error'

export enum PostgresUsage {
    COMMON, // Main PG master with common tables, we need to move as many queries away from it as possible
    COMMON_READ, // Read replica on the common tables, uses need to account for possible replication delay
    PLUGIN_STORAGE, // Plugin Storage table, no read replica for it
}

export class PostgresRouter {
    pools: Map<PostgresUsage, Pool>

    constructor(serverConfig: PluginsServerConfig) {
        status.info('🤔', `Connecting to common Postgresql...`)
        const commonClient = createPostgresPool(serverConfig.DATABASE_URL)
        status.info('👍', `Common Postgresql ready`)
        // We fill the pools maps with the default client by default as a safe fallback for hobby,
        // the rest of the constructor overrides entries if more database URLs are passed.
        this.pools = new Map([
            [PostgresUsage.COMMON, commonClient],
            [PostgresUsage.COMMON_READ, commonClient],
            [PostgresUsage.PLUGIN_STORAGE, commonClient],
        ])

        if (serverConfig.DATABASE_READONLY_URL) {
            status.info('🤔', `Connecting to read-only common Postgresql...`)
            this.pools.set(PostgresUsage.COMMON_READ, createPostgresPool(serverConfig.DATABASE_READONLY_URL))
            status.info('👍', `Read-only common Postgresql ready`)
        }
        if (serverConfig.PLUGIN_STORAGE_DATABASE_URL) {
            status.info('🤔', `Connecting to plugin-storage Postgresql...`)
            this.pools.set(PostgresUsage.PLUGIN_STORAGE, createPostgresPool(serverConfig.PLUGIN_STORAGE_DATABASE_URL))
            status.info('👍', `Plugin-storage Postgresql ready`)
        }
    }

    public postgresQuery<R extends QueryResultRow = any, I extends any[] = any[]>(
        usage: PostgresUsage,
        queryString: string | QueryConfig<I>,
        values: I | undefined,
        tag: string,
        statsd?: StatsD
    ): Promise<QueryResult<R>> {
        const wrappedTag = `${PostgresUsage[usage]}<${tag}>`
        return postgresQuery(this.pools.get(usage)!, queryString, values, wrappedTag, statsd)
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
