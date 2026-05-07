import { parseClickhouseConnectionString } from './clickhouse'
import { parseMssqlConnectionString } from './mssql'
import { parseMysqlConnectionString } from './mysql'
import { parsePostgresConnectionString } from './postgres'
import { parseSnowflakeConnectionString } from './snowflake'
import type { ConnectionStringParser, ParseResult } from './types'

const PARSERS: Record<string, ConnectionStringParser> = {
    Postgres: (str) => parsePostgresConnectionString(str, { defaultPort: 5432 }),
    Supabase: (str) => parsePostgresConnectionString(str, { defaultPort: 5432 }),
    Redshift: (str) => parsePostgresConnectionString(str, { defaultPort: 5439 }),
    MySQL: parseMysqlConnectionString,
    MSSQL: parseMssqlConnectionString,
    ClickHouse: parseClickhouseConnectionString,
    Snowflake: parseSnowflakeConnectionString,
}

export const SUPPORTS_CONNECTION_STRING: ReadonlySet<string> = new Set(Object.keys(PARSERS))

export function parseConnectionStringForSource(sourceName: string, str: string): ParseResult {
    const parser = PARSERS[sourceName]
    if (!parser) {
        return { isValid: false, fields: [] }
    }
    return parser(str)
}

export type { ParseResult, ParsedField, ConnectionStringParser } from './types'
