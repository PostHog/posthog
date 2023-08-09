// Postgres

import { StatsD } from 'hot-shots'
import { Client, Pool, PoolClient, QueryConfig, QueryResult, QueryResultRow } from 'pg'

import { instrumentQuery } from '../../utils/metrics'
import { POSTGRES_UNAVAILABLE_ERROR_MESSAGES } from './db'
import { DependencyUnavailableError } from './error'

export function postgresQuery<R extends QueryResultRow = any, I extends any[] = any[]>(
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
