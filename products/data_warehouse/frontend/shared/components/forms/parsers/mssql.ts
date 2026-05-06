import type { ParseResult, ParsedField } from './types'

const DEFAULT_PORT = 1433

export function parseMssqlConnectionString(str: string): ParseResult {
    let normalized = str
    if (normalized.startsWith('sqlserver://')) {
        normalized = 'mssql://' + normalized.substring('sqlserver://'.length)
    } else if (!normalized.startsWith('mssql://')) {
        return { isValid: false, fields: [] }
    }

    let result: URL
    try {
        result = new URL(normalized)
    } catch {
        return { isValid: false, fields: [] }
    }

    const user = decodeURIComponent(result.username || '')
    const password = decodeURIComponent(result.password || '')
    const host = decodeURIComponent(result.hostname || '')
    const port = result.port || String(DEFAULT_PORT)
    const database = result.pathname.slice(1) ? decodeURIComponent(result.pathname.slice(1)) : ''

    if (!user || !host || !database) {
        return { isValid: false, fields: [] }
    }

    const fields: ParsedField[] = [
        { path: ['host'], value: host },
        { path: ['port'], value: port },
        { path: ['database'], value: database },
        { path: ['user'], value: user },
        { path: ['password'], value: password },
    ]

    return { isValid: true, fields }
}
