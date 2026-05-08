import { parseClickhouseConnectionString } from './clickhouse'
import { parseConnectionStringForSource, SUPPORTS_CONNECTION_STRING } from './index'
import { parseMssqlConnectionString } from './mssql'
import { parseMysqlConnectionString } from './mysql'
import { parsePostgresConnectionString } from './postgres'
import { parseSnowflakeConnectionString } from './snowflake'
import type { ParsedField } from './types'

const fieldMap = (fields: ParsedField[]): Record<string, unknown> => {
    const out: Record<string, unknown> = {}
    for (const { path, value } of fields) {
        out[path.join('.')] = value
    }
    return out
}

describe('parsePostgresConnectionString', () => {
    const opts = { defaultPort: 5432 }

    it('parses a full postgres URL', () => {
        const result = parsePostgresConnectionString('postgres://alice:s3cret@db.example.com:6543/analytics', opts)
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields)).toEqual({
            host: 'db.example.com',
            port: '6543',
            database: 'analytics',
            user: 'alice',
            password: 's3cret',
        })
    })

    it('falls back to defaultPort when port is omitted', () => {
        const result = parsePostgresConnectionString('postgresql://alice:s3cret@db/analytics', opts)
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).port).toBe('5432')
    })

    it('uses the redshift defaultPort the dispatcher passes in', () => {
        const result = parsePostgresConnectionString('redshift://alice:s3cret@cluster/analytics', { defaultPort: 5439 })
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).port).toBe('5439')
    })

    it('decodes percent-encoded passwords', () => {
        const result = parsePostgresConnectionString(
            'postgres://alice:p%40ss%2Fword%3A%21@db.example.com:5432/analytics',
            opts
        )
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).password).toBe('p@ss/word:!')
    })

    it('rejects unrelated schemes', () => {
        expect(parsePostgresConnectionString('mysql://alice:s3cret@db/analytics', opts).isValid).toBe(false)
    })

    it('rejects URLs missing user, host, or database', () => {
        expect(parsePostgresConnectionString('postgres://alice@/analytics', opts).isValid).toBe(false)
        expect(parsePostgresConnectionString('postgres://alice:s3cret@db.example.com/', opts).isValid).toBe(false)
        expect(parsePostgresConnectionString('postgres://db.example.com/analytics', opts).isValid).toBe(false)
    })
})

describe('parseMysqlConnectionString', () => {
    it('parses a mysql URL', () => {
        const result = parseMysqlConnectionString('mysql://root:hunter2@10.0.0.1:3307/sales')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields)).toEqual({
            host: '10.0.0.1',
            port: '3307',
            database: 'sales',
            user: 'root',
            password: 'hunter2',
        })
    })

    it('uses default port 3306 when missing', () => {
        const result = parseMysqlConnectionString('mysql://root:hunter2@db/sales')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).port).toBe('3306')
    })

    it('emits using_ssl when ssl=false is specified', () => {
        const result = parseMysqlConnectionString('mysql://root:hunter2@db:3306/sales?ssl=false')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).using_ssl).toBe('false')
    })

    it('emits using_ssl when useSSL=true is specified', () => {
        const result = parseMysqlConnectionString('mysql://root:hunter2@db:3306/sales?useSSL=true')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).using_ssl).toBe('true')
    })

    it('does not emit using_ssl when no ssl param is present', () => {
        const result = parseMysqlConnectionString('mysql://root:hunter2@db:3306/sales')
        expect(fieldMap(result.fields).using_ssl).toBeUndefined()
    })

    it('rejects non-mysql URLs', () => {
        expect(parseMysqlConnectionString('postgres://root:hunter2@db/sales').isValid).toBe(false)
    })
})

describe('parseMssqlConnectionString', () => {
    it('parses a mssql URL', () => {
        const result = parseMssqlConnectionString('mssql://sa:Strong!@db.example.com:1434/billing')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields)).toEqual({
            host: 'db.example.com',
            port: '1434',
            database: 'billing',
            user: 'sa',
            password: 'Strong!',
        })
    })

    it('accepts the sqlserver:// scheme as an alias', () => {
        const result = parseMssqlConnectionString('sqlserver://sa:Strong!@db.example.com/billing')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).host).toBe('db.example.com')
    })

    it('uses default port 1433 when missing', () => {
        const result = parseMssqlConnectionString('mssql://sa:Strong!@db.example.com/billing')
        expect(fieldMap(result.fields).port).toBe('1433')
    })

    it('rejects JDBC and ADO style strings', () => {
        expect(
            parseMssqlConnectionString('Server=tcp:db.example.com,1433;Database=billing;User Id=sa;Password=hunter2;')
                .isValid
        ).toBe(false)
        expect(parseMssqlConnectionString('jdbc:sqlserver://db.example.com:1433;database=billing').isValid).toBe(false)
    })
})

describe('parseClickhouseConnectionString', () => {
    it('parses an https URL with secure=true and default port 8443', () => {
        const result = parseClickhouseConnectionString('https://default:pw@play.clickhouse.com/default')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields)).toEqual({
            host: 'play.clickhouse.com',
            port: '8443',
            database: 'default',
            user: 'default',
            password: 'pw',
            secure: 'true',
        })
    })

    it('parses an http URL with secure=false and default port 8123', () => {
        const result = parseClickhouseConnectionString('http://default:pw@localhost/default')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).secure).toBe('false')
        expect(fieldMap(result.fields).port).toBe('8123')
    })

    it('parses a clickhouse:// URL with secure=false and default port 9000', () => {
        const result = parseClickhouseConnectionString('clickhouse://default:pw@localhost/default')
        expect(fieldMap(result.fields).secure).toBe('false')
        expect(fieldMap(result.fields).port).toBe('9000')
    })

    it('parses a clickhouses:// URL as secure with default port 9440', () => {
        const result = parseClickhouseConnectionString('clickhouses://default:pw@localhost/default')
        expect(fieldMap(result.fields).secure).toBe('true')
        expect(fieldMap(result.fields).port).toBe('9440')
    })

    it('honors ?secure=true override on a clickhouse:// URL and switches default to 9440 (native family)', () => {
        const result = parseClickhouseConnectionString('clickhouse://default:pw@localhost/default?secure=true')
        expect(fieldMap(result.fields).secure).toBe('true')
        expect(fieldMap(result.fields).port).toBe('9440')
    })

    it('honors ?secure=true override on an http:// URL and switches default to 8443 (HTTP family)', () => {
        const result = parseClickhouseConnectionString('http://default:pw@localhost/default?secure=true')
        expect(fieldMap(result.fields).secure).toBe('true')
        expect(fieldMap(result.fields).port).toBe('8443')
    })

    it('honors ?secure=false override on an https:// URL and switches default to 8123 (HTTP family)', () => {
        const result = parseClickhouseConnectionString('https://default:pw@localhost/default?secure=false')
        expect(fieldMap(result.fields).secure).toBe('false')
        expect(fieldMap(result.fields).port).toBe('8123')
    })

    it('respects an explicit port over the scheme default', () => {
        const result = parseClickhouseConnectionString('https://default:pw@play.clickhouse.com:8123/default')
        expect(fieldMap(result.fields).port).toBe('8123')
    })

    it('rejects unsupported schemes', () => {
        expect(parseClickhouseConnectionString('postgres://default:pw@host/default').isValid).toBe(false)
    })
})

describe('parseSnowflakeConnectionString', () => {
    it('parses an account-id URL with database, schema, warehouse, and role', () => {
        const result = parseSnowflakeConnectionString(
            'snowflake://alice:hunter2@xy12345.us-east-1/MY_DB/PUBLIC?warehouse=COMPUTE_WH&role=ANALYST'
        )
        expect(result.isValid).toBe(true)
        const map = fieldMap(result.fields)
        expect(map.account_id).toBe('xy12345.us-east-1')
        expect(map.database).toBe('MY_DB')
        expect(map.schema).toBe('PUBLIC')
        expect(map.warehouse).toBe('COMPUTE_WH')
        expect(map.role).toBe('ANALYST')
    })

    it('selects the password auth_type and writes credentials to the nested path', () => {
        const result = parseSnowflakeConnectionString('snowflake://alice:hunter2@xy12345/MY_DB')
        const map = fieldMap(result.fields)
        expect(map['auth_type.selection']).toBe('password')
        expect(map['auth_type.user']).toBe('alice')
        expect(map['auth_type.password']).toBe('hunter2')
    })

    it('omits role/schema/warehouse when not provided', () => {
        const result = parseSnowflakeConnectionString('snowflake://alice:hunter2@xy12345/MY_DB')
        const paths = result.fields.map((f) => f.path.join('.'))
        expect(paths).not.toContain('role')
        expect(paths).not.toContain('schema')
        expect(paths).not.toContain('warehouse')
    })

    it('does not emit auth_type fields when the URL has no password (preserves existing keypair selection)', () => {
        const result = parseSnowflakeConnectionString('snowflake://alice@xy12345/MY_DB?warehouse=COMPUTE_WH')
        expect(result.isValid).toBe(true)
        const paths = result.fields.map((f) => f.path.join('.'))
        expect(paths).not.toContain('auth_type.selection')
        expect(paths).not.toContain('auth_type.user')
        expect(paths).not.toContain('auth_type.password')
        // non-auth fields still get populated
        expect(fieldMap(result.fields).account_id).toBe('xy12345')
        expect(fieldMap(result.fields).warehouse).toBe('COMPUTE_WH')
    })

    it('rejects URLs missing user, account, or database', () => {
        // password may be empty (Snowflake supports passwordless SSO), but user/account/db are required
        expect(parseSnowflakeConnectionString('snowflake://@xy12345/MY_DB').isValid).toBe(false)
        expect(parseSnowflakeConnectionString('snowflake://alice:pw@/MY_DB').isValid).toBe(false)
        expect(parseSnowflakeConnectionString('snowflake://alice:pw@xy12345').isValid).toBe(false)
    })

    it('parses the JDBC-style URL with credentials and database in query params', () => {
        const result = parseSnowflakeConnectionString(
            'snowflake://xy12345.snowflakecomputing.com/?user=alice&password=hunter2&warehouse=mywh&db=mydb&schema=public'
        )
        expect(result.isValid).toBe(true)
        const map = fieldMap(result.fields)
        expect(map.account_id).toBe('xy12345.snowflakecomputing.com')
        expect(map.database).toBe('mydb')
        expect(map.schema).toBe('public')
        expect(map.warehouse).toBe('mywh')
        expect(map['auth_type.selection']).toBe('password')
        expect(map['auth_type.user']).toBe('alice')
        expect(map['auth_type.password']).toBe('hunter2')
    })

    it('accepts `database` as an alias for `db` in the query-param shape', () => {
        const result = parseSnowflakeConnectionString('snowflake://xy12345/?user=alice&password=pw&database=MY_DB')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).database).toBe('MY_DB')
    })

    it('prefers userinfo and pathname over query params when both are present', () => {
        const result = parseSnowflakeConnectionString(
            'snowflake://alice:pw@xy12345/REAL_DB?user=ignored&password=ignored&db=ignored'
        )
        expect(result.isValid).toBe(true)
        const map = fieldMap(result.fields)
        expect(map.database).toBe('REAL_DB')
        expect(map['auth_type.user']).toBe('alice')
        expect(map['auth_type.password']).toBe('pw')
    })
})

describe('parseConnectionStringForSource dispatcher', () => {
    it('returns a parser for every supported source name', () => {
        expect([...SUPPORTS_CONNECTION_STRING].sort()).toEqual(
            ['ClickHouse', 'MSSQL', 'MySQL', 'Postgres', 'Redshift', 'Snowflake', 'Supabase'].sort()
        )
    })

    it('routes Postgres to the postgres parser with port 5432', () => {
        const result = parseConnectionStringForSource('Postgres', 'postgres://alice:s3cret@db/analytics')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).port).toBe('5432')
    })

    it('routes Redshift to the postgres parser with port 5439', () => {
        const result = parseConnectionStringForSource('Redshift', 'redshift://alice:s3cret@cluster/dev')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).port).toBe('5439')
    })

    it('routes Supabase to the postgres parser with port 5432', () => {
        const result = parseConnectionStringForSource('Supabase', 'postgresql://alice:s3cret@host/db')
        expect(result.isValid).toBe(true)
        expect(fieldMap(result.fields).port).toBe('5432')
    })

    it('returns isValid=false for an unknown source name', () => {
        const result = parseConnectionStringForSource('NotARealSource', 'mysql://root:pw@db/sales')
        expect(result).toEqual({ isValid: false, fields: [] })
    })

    it('returns isValid=false when the URL does not match the source', () => {
        expect(parseConnectionStringForSource('MySQL', 'postgres://root:pw@db/sales').isValid).toBe(false)
    })
})
