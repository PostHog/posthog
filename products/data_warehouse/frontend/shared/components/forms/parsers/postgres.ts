// URL-parsing logic adapted from https://github.com/brianc/node-postgres/tree/master/packages/pg-connection-string
// Copyright (c) 2010-2014 Brian Carlson (brian.m.carlson@gmail.com)
// MIT License

import type { ParseResult, ParsedField } from './types'

interface PostgresParserOptions {
    defaultPort: number
}

export function parsePostgresConnectionString(str: string, options: PostgresParserOptions): ParseResult {
    let normalized = str
    if (normalized.startsWith('postgres://')) {
        normalized = 'postgresql://' + normalized.substring('postgres://'.length)
    } else if (normalized.startsWith('redshift://')) {
        normalized = 'postgresql://' + normalized.substring('redshift://'.length)
    } else if (!normalized.startsWith('postgresql://')) {
        return { isValid: false, fields: [] }
    }

    if (/ |%[^a-f0-9]|%[a-f0-9][^a-f0-9]/i.test(normalized)) {
        normalized = encodeURI(normalized).replace(/%25(\d\d)/g, '%$1')
    }

    let result: URL
    let dummyHost = false
    try {
        result = new URL(normalized, 'postgresql://base')
    } catch {
        try {
            result = new URL(normalized.replace('@/', '@___DUMMY___/'), 'postgresql://base')
            dummyHost = true
        } catch {
            return { isValid: false, fields: [] }
        }
    }

    const params: Record<string, string> = {}
    for (const [key, value] of result.searchParams.entries()) {
        params[key] = value
    }

    const user = params.user || decodeURIComponent(result.username || '')
    const password = params.password || decodeURIComponent(result.password || '')

    const hostname = dummyHost ? '' : result.hostname
    const host = params.host || decodeURIComponent(hostname)
    const port = params.port || result.port || String(options.defaultPort)
    const pathname = result.pathname.slice(1) || ''
    const database = pathname ? decodeURIComponent(pathname) : ''

    if (!user || !database || !host) {
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
