import { z } from 'zod'

import { parser } from '@/core/schema'

// Where a PostHog lives: an http or https origin, plus the path a self-hosted PostHog can sit under,
// such as https://example.com/posthog. It has no trailing slash, query, fragment or password, so
// two ways to write one host compare equal and a token never goes to a URL with extra parts.
export const HostSchema = z
    .string({ error: 'The host must be a URL, like https://us.posthog.com.' })
    .check((ctx) => {
        const problem = hostProblem(ctx.value)
        if (problem) {
            ctx.issues.push({ code: 'custom', input: ctx.value, message: problem, abort: true })
        }
    })
    .overwrite((value) => {
        const url = new URL(value)
        return `${url.origin}${url.pathname.replace(/\/+$/, '')}`
    })
    .brand<'Host'>()

export type Host = z.output<typeof HostSchema>

// The messages never repeat the value, because it can hold a password or a token in its query.
function hostProblem(value: string): string | undefined {
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

export const parseHost = parser(HostSchema, { code: 'invalid_host' })

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
