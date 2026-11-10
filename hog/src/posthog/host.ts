import { z } from 'zod'

import { parseOrThrow, type ParseFailure } from '@/core/schema'

// An http or https origin, plus the path a self-hosted PostHog can sit under. It is normalized, so
// two ways to write one host compare equal.
export const HostSchema = z
    .string({ error: 'The host must be a URL, like https://us.posthog.com.' })
    .check((ctx) => {
        const message = validateHost(ctx.value)
        if (message) {
            ctx.issues.push({ code: 'custom', input: ctx.value, message, abort: true })
        }
    })
    .overwrite((value) => {
        const url = new URL(value)
        return `${url.origin}${url.pathname.replace(/\/+$/, '')}`
    })
    .brand<'Host'>()

export type Host = z.output<typeof HostSchema>

// The messages never repeat the value, because it can hold a password or a token in its query.
function validateHost(value: string): string | undefined {
    const url = URL.parse(value)
    if (url === null) {
        return 'The host must be a URL, like https://us.posthog.com.'
    }
    // `localhost:8000` parses with `localhost:` as its scheme, so check what the person typed.
    if (!/^https?:\/\//i.test(value)) {
        return 'The host must start with https:// or http://, like https://us.posthog.com.'
    }
    if (url.username || url.password) {
        return 'The host must not have a user name or password in it.'
    }
    if (url.search || url.hash) {
        return 'The host must not have a query (?) or a fragment (#) in it.'
    }
    return undefined
}

export function parseHost(raw: unknown, failure?: Partial<ParseFailure>): Host {
    return parseOrThrow(HostSchema, raw, { code: 'invalid_host', ...failure })
}

export const REGIONS = { us: parseHost('https://us.posthog.com'), eu: parseHost('https://eu.posthog.com') }

// A posthog.json comes with the repository, so it only picks between the PostHog Cloud regions. Any
// other host needs --host or HOG_HOST, so a repository can't send a person's login or a CI job's
// token elsewhere.
export function cloudRegion(host: Host | undefined): Host | undefined {
    return host && Object.values(REGIONS).find((region) => hostKey(region) === hostKey(host))
}

// The origin of a host, without its path: its scheme, host name and port. Every map of logins is
// keyed by it. Only `hostKey` makes one.
export type HostKey = string & z.$brand<'HostKey'>

export function hostKey(host: Host): HostKey {
    return new URL(host).origin as HostKey
}

// Keeps the path a self-hosted PostHog can sit under, such as https://example.com/posthog.
export function hostUrl(host: Host, path: string): URL {
    return new URL(path, `${host}/`)
}
