// Postgres
import { Pool, QueryConfig, QueryResult, QueryResultRow } from 'pg'
import { config } from '../config'
import { createLogger } from './logger'

const logger = createLogger('postgres')

function createPostgresPool(connectionString: string, onError?: (error: Error) => any): Pool {
    const pgPool = new Pool({
        connectionString,
        idleTimeoutMillis: 500,
        max: 10,
        ssl: process.env.DYNO // Means we are on Heroku
            ? {
                  rejectUnauthorized: false,
              }
            : undefined,
    })

    const handleError =
        onError ||
        ((error) => {
            logger.error('🔴', 'PostgreSQL error encountered!\n', error)
        })

    pgPool.on('error', handleError)

    return pgPool
}

const postgresClient = createPostgresPool(config.postgres.databaseUrl)

export function getFinalPostgresQuery(queryString: string, values: any[]): string {
    return queryString.replace(/\$([0-9]+)/g, (m, v) => JSON.stringify(values[parseInt(v) - 1]))
}

export async function postgresQuery<R extends QueryResultRow = any, I extends any[] = any[]>(
    queryString: string | QueryConfig<I>,
    values: I | undefined,
    tag: string
): Promise<QueryResult<R>> {
    let fullQuery = ''
    try {
        if (typeof queryString === 'string') {
            fullQuery = getFinalPostgresQuery(queryString, values as any[])
        } else {
            fullQuery = getFinalPostgresQuery(queryString.text, queryString.values as any[])
        }
    } catch {}

    const queryConfig =
        typeof queryString === 'string'
            ? {
                  // Annotate query string to give context when looking at DB logs
                  text: `/* automation:${tag} */ ${queryString}`,
                  values,
              }
            : queryString

    return await postgresClient.query(queryConfig, values)
}
