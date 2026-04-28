import type { ParseResult, ParsedField } from './types'

interface SchemeDefaults {
    secure: 'true' | 'false'
    port: number
}

const SCHEME_DEFAULTS: Record<string, SchemeDefaults> = {
    'https:': { secure: 'true', port: 8443 },
    'clickhouses:': { secure: 'true', port: 9440 },
    'http:': { secure: 'false', port: 8123 },
    'clickhouse:': { secure: 'false', port: 9000 },
}

const TRUTHY = new Set(['true', '1', 'yes'])
const FALSY = new Set(['false', '0', 'no'])

function overrideSecure(params: URLSearchParams): 'true' | 'false' | undefined {
    const raw = params.get('secure')
    if (raw === null) {
        return undefined
    }
    const lowered = raw.toLowerCase()
    if (TRUTHY.has(lowered)) {
        return 'true'
    }
    if (FALSY.has(lowered)) {
        return 'false'
    }
    return undefined
}

export function parseClickhouseConnectionString(str: string): ParseResult {
    let result: URL
    try {
        result = new URL(str)
    } catch {
        return { isValid: false, fields: [] }
    }

    const defaults = SCHEME_DEFAULTS[result.protocol]
    if (!defaults) {
        return { isValid: false, fields: [] }
    }

    const user = decodeURIComponent(result.username || '')
    const password = decodeURIComponent(result.password || '')
    const host = decodeURIComponent(result.hostname || '')
    const database = result.pathname.slice(1) ? decodeURIComponent(result.pathname.slice(1)) : ''

    if (!user || !host || !database) {
        return { isValid: false, fields: [] }
    }

    const secureOverride = overrideSecure(result.searchParams)
    const secure = secureOverride ?? defaults.secure
    // When the user flips the secure flag via query param against the scheme default,
    // pick the scheme's "other" canonical port so the form lands on something sensible.
    const inferredPort =
        secureOverride && secureOverride !== defaults.secure ? (secure === 'true' ? 9440 : 9000) : defaults.port
    const port = result.port || String(inferredPort)

    const fields: ParsedField[] = [
        { path: ['host'], value: host },
        { path: ['port'], value: port },
        { path: ['database'], value: database },
        { path: ['user'], value: user },
        { path: ['password'], value: password },
        { path: ['secure'], value: secure },
    ]

    return { isValid: true, fields }
}
