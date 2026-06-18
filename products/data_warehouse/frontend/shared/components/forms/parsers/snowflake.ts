import type { ParseResult, ParsedField } from './types'

export function parseSnowflakeConnectionString(str: string): ParseResult {
    if (!str.startsWith('snowflake://')) {
        return { isValid: false, fields: [] }
    }

    let result: URL
    try {
        result = new URL(str)
    } catch {
        return { isValid: false, fields: [] }
    }

    // Snowflake URLs come in two shapes in the wild: the canonical SQLAlchemy/dlt form
    // (`snowflake://user:pw@account/db/schema?warehouse=...`) and a JDBC-influenced form
    // that puts credentials and database in query params. Prefer userinfo/pathname when
    // present, fall back to the query-param shape so paste-to-fill works for either.
    const params = result.searchParams
    const user = decodeURIComponent(result.username || '') || params.get('user') || ''
    const password = decodeURIComponent(result.password || '') || params.get('password') || ''
    const accountId = decodeURIComponent(result.hostname || '')

    const segments = result.pathname.split('/').filter(Boolean).map(decodeURIComponent)
    const database = segments[0] || params.get('db') || params.get('database') || ''
    const schema = segments[1] || params.get('schema') || ''

    if (!user || !accountId || !database) {
        return { isValid: false, fields: [] }
    }

    const fields: ParsedField[] = [
        { path: ['account_id'], value: accountId },
        { path: ['database'], value: database },
    ]

    if (schema) {
        fields.push({ path: ['schema'], value: schema })
    }

    const warehouse = params.get('warehouse')
    if (warehouse) {
        fields.push({ path: ['warehouse'], value: warehouse })
    }

    const role = params.get('role')
    if (role) {
        fields.push({ path: ['role'], value: role })
    }

    // The URL form can only carry user + password (not a private key). Only flip
    // auth_type to "password" when the URL actually carries a password — otherwise
    // a user pasting a URL just to grab account_id/warehouse would silently lose
    // an existing keypair selection.
    if (password) {
        fields.push(
            { path: ['auth_type', 'selection'], value: 'password' },
            { path: ['auth_type', 'user'], value: user },
            { path: ['auth_type', 'password'], value: password }
        )
    }

    return { isValid: true, fields }
}
