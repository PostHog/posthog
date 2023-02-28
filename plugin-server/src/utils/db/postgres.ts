// Postgres

import { StatsD } from 'hot-shots'
import { Client, Pool, PoolClient, QueryResult, QueryResultRow } from 'pg'

import { instrumentQuery } from '../../utils/metrics'
import { POSTGRES_UNAVAILABLE_ERROR_MESSAGES } from './db'
import { DependencyUnavailableError } from './error'
import { getFinalPostgresQuery, timeoutGuard } from './utils'

export function postgresQuery<R extends QueryResultRow = any, I extends any[] = any[]>(
    client: Client | Pool | PoolClient,
    queryString: string,
    values: I | undefined,
    tag: string,
    statsd?: StatsD
): Promise<QueryResult<R>> {
    return instrumentQuery(statsd, 'query.postgres', tag, async () => {
        let fullQuery = ''
        try {
            fullQuery = getFinalPostgresQuery(queryString, values as any[])
        } catch {}
        const timeout = timeoutGuard('Postgres slow query warning after 30 sec', {
            queryString,
            values,
            fullQuery,
        })

        // Annotate query string to give context when looking at DB logs
        queryString = `/* plugin-server:${tag} */ ${queryString}`
        try {
            return await client.query(queryString, values)
        } catch (error) {
            if (
                error.message &&
                POSTGRES_UNAVAILABLE_ERROR_MESSAGES.some((message) => error.message.includes(message))
            ) {
                throw new DependencyUnavailableError(error.message, 'Postgres', error)
            }
            throw error
        } finally {
            clearTimeout(timeout)
        }
    })
}
