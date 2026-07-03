import { safeDecodeURIComponent } from './decode'
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

    const user = safeDecodeURIComponent(result.username || '')
    const password = safeDecodeURIComponent(result.password || '')
    const host = safeDecodeURIComponent(result.hostname || '')
    const port = result.port || String(DEFAULT_PORT)
    const database = result.pathname.slice(1) ? safeDecodeURIComponent(result.pathname.slice(1)) : ''

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
