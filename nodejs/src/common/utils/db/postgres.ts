// Postgres
import { DateTime } from 'luxon'
import { hostname } from 'os'
import { Client, Pool, PoolClient, QueryConfig, QueryResult, QueryResultRow, types as pgTypes } from 'pg'

import { withSpan } from '~/common/tracing/tracing-utils'

import { logger } from '../logger'
import { createPostgresPool } from '../utils'
import { DependencyUnavailableError } from './error'
import {
    postgresClientErrorCounter,
    postgresClientRemovedInUseCounter,
    postgresErrorCounter,
    postgresLongOpenTransactionCounter,
    postgresOpenAtShutdownCounter,
    postgresOpenTransactionsGauge,
    postgresPoolAcquireDurationHistogram,
    postgresPoolClientEventsCounter,
    postgresTransactionCounter,
    postgresTransactionDurationHistogram,
} from './metrics'
import { timeoutGuard } from './utils'

/** Config that PostgresRouter needs to create its connection pools. */
export type PostgresRouterConfig = {
    DATABASE_URL: string
    POSTGRES_CONNECTION_POOL_SIZE: number
    DATABASE_READONLY_URL?: string
    PLUGIN_STORAGE_DATABASE_URL?: string
    PERSONS_DATABASE_URL?: string
    PERSONS_READONLY_DATABASE_URL?: string
    BEHAVIORAL_COHORTS_DATABASE_URL?: string
}

// By default node-postgres returns dates as JS Date objects using the local timezone.
// We need UTC ISO strings instead. This must be called before creating any Pool.
// Idempotent — safe to call multiple times (e.g. from both hub.ts and PostgresRouter).
let typeParsersInstalled = false
export function installPostgresTypeParsers(): void {
    if (typeParsersInstalled) {
        return
    }
    typeParsersInstalled = true

    pgTypes.setTypeParser(1083 /* types.TypeId.TIME */, (timeStr) =>
        timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
    )
    pgTypes.setTypeParser(1114 /* types.TypeId.TIMESTAMP */, (timeStr) =>
        timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
    )
    pgTypes.setTypeParser(1184 /* types.TypeId.TIMESTAMPTZ */, (timeStr) =>
        timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
    )
}

const POSTGRES_UNAVAILABLE_ERROR_MESSAGES = [
    'connection to server at',
    'could not translate host',
    'server conn crashed',
    'no more connections allowed',
    'server closed the connection unexpectedly',
    'getaddrinfo EAI_AGAIN',
    'Connection terminated unexpectedly',
    'ECONNREFUSED',
    'ECONNRESET', // Connection reset by peer, e.g. PgBouncer/PG closed an idle or in-flight connection
    'EHOSTUNREACH', // No route to host, e.g. the PgBouncer pod's IP vanished during a restart
    'ETIMEDOUT',
    'query_wait_timeout', // Waiting on PG bouncer to give us a slot
    'server login has been failing', // PgBouncer cannot authenticate with upstream PG
    'pooler is shutting down', // PgBouncer terminating client connections during a restart
    'Cannot use a pool after calling end on the pool', // Shutdown ended the pool while work was still in flight
]

export function isTransientPgError(err: unknown): boolean {
    const message = (err as Error | undefined)?.message
    return !!message && POSTGRES_UNAVAILABLE_ERROR_MESSAGES.some((m) => message.includes(m))
}

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
    /** Statement currently in flight, so a connection lost mid-transaction can be attributed to it. */
    inFlightTag: string = 'none'
    /** Last statement that finished, which names where a stalled transaction stopped progressing. */
    lastCompletedTag: string = 'none'

    constructor(target: PostgresUse, client: PoolClient) {
        this.target = target
        this.client = client
    }
}

type OpenTransaction = { pool: string; tag: string; client: TransactionClient }

/** Process-wide, so shutdown can name the transactions that never finished. */
const openTransactions = new Set<OpenTransaction>()

function openTransactionFor(client: PoolClient): OpenTransaction | undefined {
    for (const open of openTransactions) {
        if (open.client.client === client) {
            return open
        }
    }
    return undefined
}

/** Pool client churn is invisible from inside the app without these. */
export function instrumentPool(pool: Pool, poolLabel: string): Pool {
    pool.on('connect', () => postgresPoolClientEventsCounter.inc({ pool: poolLabel, event: 'connect' }))
    pool.on('acquire', () => postgresPoolClientEventsCounter.inc({ pool: poolLabel, event: 'acquire' }))
    pool.on('remove', (client: PoolClient) => {
        postgresPoolClientEventsCounter.inc({ pool: poolLabel, event: 'remove' })
        // A transaction deregisters before releasing, so anything still here was torn down under.
        const open = openTransactionFor(client)
        if (open) {
            postgresClientRemovedInUseCounter.inc({
                pool: poolLabel,
                tag: open.tag,
                in_flight: open.client.inFlightTag,
            })
            logger.warn('🔌', 'Postgres pool removed a client mid-transaction', {
                pool: poolLabel,
                tag: open.tag,
                inFlight: open.client.inFlightTag,
                lastCompleted: open.client.lastCompletedTag,
            })
        }
    })
    return pool
}

export class PostgresRouter {
    private pools: Map<PostgresUse, Pool>

    constructor(serverConfig: PostgresRouterConfig, appName?: string) {
        installPostgresTypeParsers()

        // Postgres truncates application_name at 63 bytes. The mode stays the prefix so existing
        // filters still match, and the hostname names the pod holding a stuck session.
        const app_name = `${appName ?? 'unknown'}/${hostname()}`.slice(0, 63)
        logger.info('🤔', `Connecting to common Postgresql...`)
        const commonClient = instrumentPool(
            createPostgresPool(serverConfig.DATABASE_URL, serverConfig.POSTGRES_CONNECTION_POOL_SIZE, app_name),
            'COMMON_WRITE'
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
                instrumentPool(
                    createPostgresPool(
                        serverConfig.DATABASE_READONLY_URL,
                        serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                        app_name
                    ),
                    'COMMON_READ'
                )
            )
            logger.info('👍', `Read-only common Postgresql ready`)
        }
        if (serverConfig.PLUGIN_STORAGE_DATABASE_URL) {
            logger.info('🤔', `Connecting to plugin-storage Postgresql...`)
            this.pools.set(
                PostgresUse.PLUGIN_STORAGE_RW,
                instrumentPool(
                    createPostgresPool(
                        serverConfig.PLUGIN_STORAGE_DATABASE_URL,
                        serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                        app_name
                    ),
                    'PLUGIN_STORAGE_RW'
                )
            )
            logger.info('👍', `Plugin-storage Postgresql ready`)
        }
        if (serverConfig.PERSONS_DATABASE_URL) {
            logger.info('🤔', `Connecting to persons Postgresql...`)
            this.pools.set(
                PostgresUse.PERSONS_WRITE,
                instrumentPool(
                    createPostgresPool(
                        serverConfig.PERSONS_DATABASE_URL,
                        serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                        app_name
                    ),
                    'PERSONS_WRITE'
                )
            )
            logger.info('👍', `Persons Postgresql ready`)
        }

        if (serverConfig.BEHAVIORAL_COHORTS_DATABASE_URL) {
            logger.info('🤔', `Connecting to behavioral cohorts Postgresql...`)
            this.pools.set(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                instrumentPool(
                    createPostgresPool(
                        serverConfig.BEHAVIORAL_COHORTS_DATABASE_URL,
                        serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                        app_name
                    ),
                    'BEHAVIORAL_COHORTS_RW'
                )
            )
            logger.info('👍', `Behavioral cohorts Postgresql ready`)
        }

        if (serverConfig.PERSONS_READONLY_DATABASE_URL) {
            logger.info('🤔', `Connecting to persons read-only Postgresql...`)
            this.pools.set(
                PostgresUse.PERSONS_READ,
                instrumentPool(
                    createPostgresPool(
                        serverConfig.PERSONS_READONLY_DATABASE_URL,
                        serverConfig.POSTGRES_CONNECTION_POOL_SIZE,
                        app_name
                    ),
                    'PERSONS_READ'
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
            target.inFlightTag = tag
            try {
                return await postgresQuery(
                    target.client,
                    queryString,
                    values,
                    wrappedTag,
                    queryFailureLogLevel,
                    target.target
                )
            } finally {
                target.lastCompletedTag = tag
                target.inFlightTag = 'none'
            }
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

        const poolLabel = PostgresUse[usage]

        return withSpan('postgres', 'query.postgres_transaction', { tag: wrappedTag }, async () => {
            // An exhausted pool waits here forever, so the acquire gets its own guard.
            const acquireGuard = timeoutGuard(
                `Postgres transaction still waiting for a pooled client!`,
                () => ({ tag: wrappedTag }),
                undefined,
                true,
                () => postgresLongOpenTransactionCounter.inc({ pool: poolLabel, tag, in_flight: 'acquiring' })
            )
            const acquireStart = performance.now()
            let client: PoolClient
            try {
                client = await this.pools.get(usage)!.connect()
            } finally {
                clearTimeout(acquireGuard)
            }
            postgresPoolAcquireDurationHistogram.observe({ pool: poolLabel }, (performance.now() - acquireStart) / 1000)

            const transactionClient = new TransactionClient(usage, client)
            const timeout = timeoutGuard(
                `Postgres slow transaction warning after 30 sec!`,
                () => ({
                    tag: wrappedTag,
                    inFlight: transactionClient.inFlightTag,
                    lastCompleted: transactionClient.lastCompletedTag,
                }),
                undefined,
                true,
                () =>
                    postgresLongOpenTransactionCounter.inc({
                        pool: poolLabel,
                        tag,
                        in_flight: transactionClient.inFlightTag,
                    })
            )
            const openEntry: OpenTransaction = { pool: poolLabel, tag, client: transactionClient }
            openTransactions.add(openEntry)
            postgresOpenTransactionsGauge.inc({ pool: poolLabel, tag })
            let clientError: Error | undefined
            // pg drops the pool's idle error listener while a client is checked out, so without
            // this an unhandled 'error' is thrown synchronously and takes the process down before
            // the rejection pg queues for the in-flight query can reach the catch below.
            const onClientError = (error: Error): void => {
                clientError = error
                postgresClientErrorCounter.inc({ pool: poolLabel, in_flight: transactionClient.inFlightTag })
                logger.warn('🔌', 'Postgres client error during transaction', {
                    tag: wrappedTag,
                    inFlight: transactionClient.inFlightTag,
                    lastCompleted: transactionClient.lastCompletedTag,
                    // An Error's own fields are non-enumerable, so it logs as {} unserialised.
                    error: String(error),
                    stack: error.stack,
                })
            }
            client.on('error', onClientError)

            const started = performance.now()
            let outcome = 'commit'
            try {
                await client.query('BEGIN')
                const response = await transaction(transactionClient)
                await client.query('COMMIT')
                return response
            } catch (e) {
                outcome = 'rollback'
                try {
                    await client.query('ROLLBACK')
                } catch (rollbackError) {
                    // A lost connection cannot roll back, and the server discards the transaction
                    // when it drops. Swallow it so the original error is the one thrown.
                    outcome = 'rollback_failed'
                    logger.warn('🔌', 'Postgres ROLLBACK failed', {
                        tag: wrappedTag,
                        error: String(rollbackError),
                    })
                }

                handlePostgresError(e, usage)

                throw e
            } finally {
                client.removeListener('error', onClientError)
                openTransactions.delete(openEntry)
                postgresOpenTransactionsGauge.dec({ pool: poolLabel, tag })
                postgresTransactionCounter.inc({ pool: poolLabel, tag, outcome })
                postgresTransactionDurationHistogram.observe(
                    { pool: poolLabel, tag, outcome },
                    (performance.now() - started) / 1000
                )
                // Passing the error destroys the client rather than returning a poisoned one.
                client.release(clientError)
                clearTimeout(timeout)
            }
        })
    }

    public async connect(usage: PostgresUse): Promise<PoolClient> {
        return await this.pools.get(usage)!.connect()
    }

    async end(): Promise<void> {
        // Ending a pool under an open transaction abandons it, so name them before closing.
        for (const open of openTransactions) {
            postgresOpenAtShutdownCounter.inc({ pool: open.pool, tag: open.tag })
            logger.warn('🔌', 'Postgres transaction still open at shutdown', {
                pool: open.pool,
                tag: open.tag,
                inFlight: open.client.inFlightTag,
                lastCompleted: open.client.lastCompletedTag,
            })
        }

        // Close all the connection pools
        const uniquePools: Set<Pool> = new Set(this.pools.values())
        for (const pool of uniquePools) {
            await pool.end()
        }
    }
}

/**
 * Scope entry for a `PostgresRouter`. `start` constructs the router
 * (which opens connection pools eagerly), `stop` ends every pool. Register
 * this in a `Scope` so the router's lifetime is tied to the scope that
 * owns it.
 */
export class PostgresRouterComponent {
    constructor(
        private readonly config: PostgresRouterConfig,
        private readonly appName?: string
    ) {}

    start(): Promise<{ value: PostgresRouter; stop: () => Promise<void> }> {
        const router = new PostgresRouter(this.config, this.appName)
        return Promise.resolve({
            value: router,
            stop: () => router.end(),
        })
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
                      // TODO: Use the plugin-server-mode tag to be extra specific
                      text: `/* nodejs:${tag} */ ${queryString}`,
                      values,
                  }
                : queryString

        try {
            return await client.query(queryConfig, values)
        } catch (error) {
            handlePostgresError(error, databaseUse)

            logger[queryFailureLogLevel]('🔴', 'Postgres query error', {
                query: queryConfig.text,
                error,
                stack: error.stack,
            })
            throw error
        }
    })
}

/** Throws retriable DependencyUnavailableError for transient PG/PgBouncer errors, does nothing otherwise. */
export function handlePostgresError(error: Error, databaseUse: PostgresUse): void {
    const matchedMessage = POSTGRES_UNAVAILABLE_ERROR_MESSAGES.find((msg) => error.message?.includes(msg))
    if (!matchedMessage) {
        return
    }

    postgresErrorCounter.inc({ error_type: matchedMessage, database_use: PostgresUse[databaseUse] })
    throw new DependencyUnavailableError(error.message, 'Postgres', error)
}
