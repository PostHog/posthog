import { z } from 'zod'

import type { Choice } from '@/core/prompts'
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

export const REGION_IDS = ['us', 'eu'] as const

export type RegionId = (typeof REGION_IDS)[number]

// The PostHog Cloud regions. `REGIONS` holds the app's host, and `INGESTION_HOSTS` where the SDKs
// send events.
export const REGIONS: Record<RegionId, Host> = {
    us: parseHost('https://us.posthog.com'),
    eu: parseHost('https://eu.posthog.com'),
}

export const INGESTION_HOSTS: Record<RegionId, Host> = {
    us: parseHost('https://us.i.posthog.com'),
    eu: parseHost('https://eu.i.posthog.com'),
}

// How a person picks a region at a terminal.
export const REGION_CHOICES: readonly Choice<RegionId>[] = [
    { value: 'us', label: 'US Cloud', hint: 'us.posthog.com' },
    { value: 'eu', label: 'EU Cloud', hint: 'eu.posthog.com' },
]

export function regionOf(host: Host | undefined): RegionId | undefined {
    return host === undefined ? undefined : REGION_IDS.find((id) => sameHost(REGIONS[id], host))
}

// A posthog.json comes with the repository, so it only picks between the PostHog Cloud regions. Any
// other host needs --host or HOG_HOST, so a repository can't send a person's login or a CI job's
// token elsewhere.
export function cloudRegion(host: Host | undefined): Host | undefined {
    const region = regionOf(host)
    return region === undefined ? undefined : REGIONS[region]
}

// The origin of a host, without its path: its scheme, host name and port. Every map of logins is
// keyed by it. Only `hostKey` makes one.
export type HostKey = string & z.$brand<'HostKey'>

export function hostKey(host: Host): HostKey {
    return new URL(host).origin as HostKey
}

export function sameHost(a: Host, b: Host): boolean {
    return hostKey(a) === hostKey(b)
}

// Keeps the path a self-hosted PostHog can sit under, such as https://example.com/posthog.
export function hostUrl(host: Host, path: string): URL {
    return new URL(path, `${host}/`)
}
