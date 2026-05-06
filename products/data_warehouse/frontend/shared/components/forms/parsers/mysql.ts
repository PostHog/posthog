import type { ParseResult, ParsedField } from './types'

const DEFAULT_PORT = 3306

// MySQL's `ssl=PREFERRED` (the server default) means "try SSL, fall back to plaintext",
// which is semantically weaker than our binary `using_ssl=true` (required). We map it
// to `'true'` anyway because the destination form is a single boolean: rounding up keeps
// the parsed default secure-by-default, and a server that genuinely cannot speak SSL
// will fail loudly rather than silently downgrading.
const TRUTHY = new Set(['true', '1', 'yes', 'required', 'preferred'])
const FALSY = new Set(['false', '0', 'no', 'disabled'])

function readSslParam(params: URLSearchParams): string | undefined {
    const candidates = ['ssl', 'useSSL', 'sslmode']
    for (const key of candidates) {
        const raw = params.get(key)
        if (raw === null) {
            continue
        }
        const lowered = raw.toLowerCase()
        if (TRUTHY.has(lowered)) {
            return 'true'
        }
        if (FALSY.has(lowered)) {
            return 'false'
        }
    }
    return undefined
}

export function parseMysqlConnectionString(str: string): ParseResult {
    if (!str.startsWith('mysql://') && !str.startsWith('mysqls://')) {
        return { isValid: false, fields: [] }
    }

    let result: URL
    try {
        result = new URL(str)
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

    const usingSsl = readSslParam(result.searchParams)
    if (usingSsl !== undefined) {
        fields.push({ path: ['using_ssl'], value: usingSsl })
    }

    return { isValid: true, fields }
}
