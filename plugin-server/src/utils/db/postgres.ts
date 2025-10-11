// Postgres
import { Client, DatabaseError, Pool, PoolClient, QueryConfig, QueryResult, QueryResultRow } from 'pg'

import { withSpan } from '~/common/tracing/tracing-utils'

import { PluginsServerConfig } from '../../types'
import { logger } from '../logger'
import { createPostgresPool } from '../utils'
import { POSTGRES_UNAVAILABLE_ERROR_MESSAGES } from './db'
import { DependencyUnavailableError } from './error'
import { postgresErrorCounter } from './metrics'
import { timeoutGuard } from './utils'

export enum PostgresUse {
    COMMON_READ, // Read replica on the common tables, uses need to account for possible replication delay
    COMMON_WRITE, // Main PG master with common tables, we need to move as many queries away from it as possible
    PLUGIN_STORAGE_RW, // Plugin Storage table, no read replica for it
    PERSONS_READ, // Person database, read replica
    PERSONS_WRITE, // Person database, write
    BEHAVIORAL_COHORTS_RW, // Behavioral cohorts database for behavioral cohorts
}

export class TransactionClient {
    readonly target: PostgresUse
    readonly client: PoolClient

    constructor(target: PostgresUse, client: PoolClient) {
        this.target = target
        this.client = client
    }
}

export class PostgresRouter {
    private pools: Map<PostgresUse, Pool>

    constructor(serverConfig: PluginsServerConfig) {
        const app_name = serverConfig.PLUGIN_SERVER_MODE ?? 'unknown'
        logger.info('🤔', `Connecting to common Postgresql...`)
        const commonClient = createPostgresPool(
            serverConfig.DATABASE_URL,
            serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
            app_name
        )
        logger.info('👍', `Common Postgresql ready`)
        // We fill the pools maps with the default client by default as a safe fallback for hobby,
        // the rest of the constructor overrides entries if more database URLs are passed.
        this.pools = new Map([
            [PostgresUse.COMMON_WRITE, commonClient],
            [PostgresUse.COMMON_READ, commonClient],
            [PostgresUse.PLUGIN_STORAGE_RW, commonClient],
            [PostgresUse.PERSONS_WRITE, commonClient],
            [PostgresUse.BEHAVIORAL_COHORTS_RW, commonClient],
        ])

        if (serverConfig.DATABASE_READONLY_URL) {
            logger.info('🤔', `Connecting to read-only common Postgresql...`)
            this.pools.set(
                PostgresUse.COMMON_READ,
                createPostgresPool(
                    serverConfig.DATABASE_READONLY_URL,
                    serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                    app_name
                )
            )
            logger.info('👍', `Read-only common Postgresql ready`)
        }
        if (serverConfig.PLUGIN_STORAGE_DATABASE_URL) {
            logger.info('🤔', `Connecting to plugin-storage Postgresql...`)
            this.pools.set(
                PostgresUse.PLUGIN_STORAGE_RW,
                createPostgresPool(
                    serverConfig.PLUGIN_STORAGE_DATABASE_URL,
                    serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                    app_name
                )
            )
            logger.info('👍', `Plugin-storage Postgresql ready`)
        }
        if (serverConfig.PERSONS_DATABASE_URL) {
            logger.info('🤔', `Connecting to persons Postgresql...`)
            this.pools.set(
                PostgresUse.PERSONS_WRITE,
                createPostgresPool(
                    serverConfig.PERSONS_DATABASE_URL,
                    serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                    app_name
                )
            )
            logger.info('👍', `Persons Postgresql ready`)
        }

        if (serverConfig.BEHAVIORAL_COHORTS_DATABASE_URL) {
            logger.info('🤔', `Connecting to behavioral cohorts Postgresql...`)
            this.pools.set(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                createPostgresPool(
                    serverConfig.BEHAVIORAL_COHORTS_DATABASE_URL,
                    serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                    app_name
                )
            )
            logger.info('👍', `Behavioral cohorts Postgresql ready`)
        }

        if (serverConfig.PERSONS_READONLY_DATABASE_URL) {
            logger.info('🤔', `Connecting to persons read-only Postgresql...`)
            this.pools.set(
                PostgresUse.PERSONS_READ,
                createPostgresPool(
                    serverConfig.PERSONS_READONLY_DATABASE_URL,
                    serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                    app_name
                )
            )
            logger.info('👍', `Persons read-only Postgresql ready`)
        } else {
            this.pools.set(PostgresUse.PERSONS_READ, this.pools.get(PostgresUse.PERSONS_WRITE)!)
            logger.info('👍', `Using persons write pool for read-only`)
        }
    }

    public async query<R extends QueryResultRow = any, I extends any[] = any[]>(
        target: PostgresUse | TransactionClient,
        queryString: string | QueryConfig<I>,
        values: I | undefined,
        tag: string,
        queryFailureLogLevel: 'error' | 'warn' = 'error'
    ): Promise<QueryResult<R>> {
        if (target instanceof TransactionClient) {
            const wrappedTag = `${PostgresUse[target.target]}:Tx<${tag}>`
            return postgresQuery(target.client, queryString, values, wrappedTag, queryFailureLogLevel, target.target)
        } else {
            const wrappedTag = `${PostgresUse[target]}<${tag}>`
            return postgresQuery(this.pools.get(target)!, queryString, values, wrappedTag, queryFailureLogLevel, target)
        }
    }

    public async transaction<ReturnType>(
        usage: PostgresUse,
        tag: string,
        transaction: (client: TransactionClient) => Promise<ReturnType>
    ): Promise<ReturnType> {
        const wrappedTag = `${PostgresUse[usage]}:Tx<${tag}>`

        return withSpan('postgres', 'query.postgres_transaction', { tag: wrappedTag }, async () => {
            const timeout = timeoutGuard(`Postgres slow transaction warning after 30 sec!`)
            const client = await this.pools.get(usage)!.connect()
            try {
                await client.query('BEGIN')
                const response = await transaction(new TransactionClient(usage, client))
                await client.query('COMMIT')
                return response
            } catch (e) {
                await client.query('ROLLBACK')

                // if Postgres is down the ROLLBACK above won't work, but the transaction shouldn't be committed either
                if (e.message && POSTGRES_UNAVAILABLE_ERROR_MESSAGES.some((message) => e.message.includes(message))) {
                    handlePostgresUnavailableError(e, usage)
                }

                throw e
            } finally {
                client.release()
                clearTimeout(timeout)
            }
        })
    }

    public async connect(usage: PostgresUse): Promise<PoolClient> {
        return await this.pools.get(usage)!.connect()
    }

    async end(): Promise<void> {
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
    queryFailureLogLevel: 'error' | 'warn' = 'error',
    databaseUse: PostgresUse
): Promise<QueryResult<R>> {
    return withSpan('postgres', 'query.postgres', { tag: tag ?? 'unknown' }, async () => {
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
                handlePostgresUnavailableError(error, databaseUse)
            }

            logger[queryFailureLogLevel]('🔴', 'Postgres query error', {
                query: queryConfig.text,
                error,
                stack: error.stack,
            })
            throw error
        }
    })
}

function handlePostgresUnavailableError(error: DatabaseError, databaseUse: PostgresUse) {
    const databaseUseLabel = PostgresUse[databaseUse]
    let errorType = 'other'

    const matchedError = POSTGRES_UNAVAILABLE_ERROR_MESSAGES.find((message) => error.message.includes(message))
    if (matchedError) {
        errorType = matchedError
    } else if (error.code) {
        errorType = error.code
    }

    postgresErrorCounter.inc({ error_type: errorType, database_use: databaseUseLabel })
    throw new DependencyUnavailableError(error.message, 'Postgres', error)
}
