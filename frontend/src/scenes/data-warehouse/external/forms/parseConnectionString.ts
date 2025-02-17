//Parse method copied from https://github.com/brianc/node-postgres/tree/master/packages/pg-connection-string
//Copyright (c) 2010-2014 Brian Carlson (brian.m.carlson@gmail.com)
//Adapted & Repurposed for TypeScript by Peter Hicks (peter.h@posthog.com)
//MIT License

interface Config {
    host?: string
    database?: string | null
    port?: string | null
    user?: string | null
    password?: string | null
    client_encoding?: string | null
    isValid?: boolean
    [key: string]: any
}

export function parseConnectionString(str: string): Config {
    const config: Config = {}
    let result: URL
    let dummyHost = false

    // Allow "postgres://" and "postgresql://"
    if (str.startsWith('postgres://')) {
        str = 'postgresql://' + str.substring('postgres://'.length)
    }

    if (/ |%[^a-f0-9]|%[a-f0-9][^a-f0-9]/i.test(str)) {
        str = encodeURI(str).replace(/%25(\d\d)/g, '%$1') // Encode spaces as %20
    }

    try {
        result = new URL(str, 'postgresql://base')
    } catch {
        // Invalid URL, attempt with dummy host
        result = new URL(str.replace('@/', '@___DUMMY___/'), 'postgresql://base')
        dummyHost = true
    }

    // Parse search parameters
    for (const [key, value] of result.searchParams.entries()) {
        config[key] = value
    }

    config.user = config.user || decodeURIComponent(result.username || '')
    config.password = config.password || decodeURIComponent(result.password || '')

    if (result.protocol === 'socket:') {
        config.host = decodeURI(result.pathname)
        config.database = result.searchParams.get('db')
        config.client_encoding = result.searchParams.get('encoding')
        return config
    }

    const hostname = dummyHost ? '' : result.hostname
    if (!config.host) {
        config.host = decodeURIComponent(hostname)
    } else if (hostname && /^%2f/i.test(hostname)) {
        result.pathname = hostname + result.pathname
    }

    config.port = config.port || result.port
    const pathname = result.pathname.slice(1) || null
    config.database = pathname ? decodeURIComponent(pathname) : null

    config.isValid = !!(config.user && config.database && config.host)

    return config
}
