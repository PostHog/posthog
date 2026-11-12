import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseJsonOrUndefined } from '@/core/json'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import { VERSION } from '@/version'

import { type Host, hostKey, hostUrl, INGESTION_HOSTS, REGION_IDS, REGIONS, sameHost } from './host'

const CATALOG_PATH = 'api/cli/catalog.json'
const CACHE_FILE = 'api-catalog.json'
const DAY_MS = 24 * 60 * 60 * 1000
const RETRY_AFTER_MS = 60 * 60 * 1000
const FETCH_TIMEOUT_MS = 5000

const CatalogEnvelopeSchema = z.object({
    schemaVersion: z.number().int(),
    minHogVersion: z.string(),
    build: z.string().nullable(),
    tools: z.array(z.unknown()),
})

type CatalogEnvelope = z.output<typeof CatalogEnvelopeSchema>

const HostCacheSchema = z.object({
    fetchedAt: z.number().nullable(),
    etag: z.string().nullable(),
    catalog: CatalogEnvelopeSchema.nullable(),
    retryAfter: z.number().nullable(),
    failure: z.object({ reason: z.string(), notServed: z.boolean() }).nullable(),
})

type HostCache = z.output<typeof HostCacheSchema>

const CacheSchema = z.object({ hosts: z.record(z.string(), HostCacheSchema) })

type Cache = z.output<typeof CacheSchema>

// Each PostHog serves the catalog of the code it runs, and a Cloud region serves it from its app host.
export function catalogUrl(host: Host): string {
    const region = REGION_IDS.find((id) => sameHost(INGESTION_HOSTS[id], host))
    return hostUrl(region ? REGIONS[region] : host, CATALOG_PATH).toString()
}

export type CatalogOrigin = 'network' | 'cache' | 'bundled'

export type BundledReason = 'pinned' | 'insecure_tls' | 'needs_newer_hog' | 'no_folder' | 'unreachable' | 'not_served'

export interface ResolvedCatalog {
    origin: CatalogOrigin
    catalog: CatalogEnvelope | undefined
    fetchedAt: number | null
    reason: string | null
    reasonCode: BundledReason | null
    previous: CatalogEnvelope | undefined
    // Set while hog waits to download again after a failed download.
    retryAfter: number | null
    downloadSkipped: boolean
}

const IDENTIFIER = /^(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)$/

function parseVersion(version: string): { core: number[]; pre: string[] } | undefined {
    const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec(version)
    const pre = match?.[4] ? match[4].split('.') : []
    if (!match || !pre.every((identifier) => IDENTIFIER.test(identifier))) {
        return undefined
    }
    return { core: [Number(match[1]), Number(match[2]), Number(match[3])], pre }
}

// SemVer precedence: numeric identifiers compare as numbers and sort before alphanumeric ones, which
// compare in ASCII order.
function compareIdentifiers(x: string, y: string): number {
    const xNumeric = /^\d+$/.test(x)
    const yNumeric = /^\d+$/.test(y)
    if (xNumeric && yNumeric) {
        return Math.sign(Number(x) - Number(y))
    }
    if (xNumeric !== yNumeric) {
        return xNumeric ? -1 : 1
    }
    return x < y ? -1 : x > y ? 1 : 0
}

export function compareVersions(a: string, b: string): number | undefined {
    const left = parseVersion(a)
    const right = parseVersion(b)
    if (!left || !right) {
        return undefined
    }
    for (let i = 0; i < 3; i++) {
        const difference = left.core[i]! - right.core[i]!
        if (difference !== 0) {
            return Math.sign(difference)
        }
    }
    if (left.pre.length === 0 || right.pre.length === 0) {
        return Math.sign(right.pre.length - left.pre.length)
    }
    for (let i = 0; i < Math.max(left.pre.length, right.pre.length); i++) {
        const x = left.pre[i]
        const y = right.pre[i]
        if (x === undefined || y === undefined) {
            return x === undefined ? -1 : 1
        }
        const order = compareIdentifiers(x, y)
        if (order !== 0) {
            return order
        }
    }
    return 0
}

// A catalog that needs a newer hog is ignored whole, so an older hog never runs plans it may read
// differently. An unreadable minHogVersion counts as newer.
function incompatibility(catalog: CatalogEnvelope): string | null {
    const order = compareVersions(VERSION, catalog.minHogVersion)
    if (order === undefined || order < 0) {
        return `the catalog needs hog ${catalog.minHogVersion} or later, and this is hog ${VERSION}`
    }
    return null
}

async function readCache(runtime: Runtime, path: string): Promise<Cache> {
    try {
        return parseJsonOrUndefined(await runtime.readFile(path), CacheSchema) ?? { hosts: {} }
    } catch {
        return { hosts: {} }
    }
}

async function writeCache(runtime: Runtime, path: string, cache: Cache): Promise<void> {
    try {
        await runtime.writePrivateFile(path, JSON.stringify(cache))
    } catch {
        // An unwritable folder means the next run downloads again.
    }
}

type Download =
    | { kind: 'catalog'; catalog: CatalogEnvelope; etag: string | null }
    | { kind: 'unchanged' }
    | { kind: 'failed'; reason: string; notServed: boolean }

async function download(runtime: Runtime, url: string, etag: string | null): Promise<Download> {
    const origin = new URL(url).origin
    try {
        const response = await runtime.fetch(url, {
            headers: etag ? { 'If-None-Match': etag } : {},
            timeoutMs: FETCH_TIMEOUT_MS,
            skipRateLimit: true,
        })
        if (response.status === 304) {
            return { kind: 'unchanged' }
        }
        if (response.status === 404) {
            return { kind: 'failed', reason: `${origin} doesn't serve a tool catalog`, notServed: true }
        }
        if (!response.ok) {
            return { kind: 'failed', reason: `${origin} answered ${response.status}`, notServed: false }
        }
        const catalog = parseJsonOrUndefined(await response.text(), CatalogEnvelopeSchema)
        if (!catalog) {
            return { kind: 'failed', reason: `${origin} sent a catalog hog can't read`, notServed: true }
        }
        return { kind: 'catalog', catalog, etag: response.headers.get('ETag') }
    } catch (error) {
        return { kind: 'failed', reason: error instanceof Error ? error.message : String(error), notServed: false }
    }
}

export interface CatalogOptions {
    host: Host
    refresh?: boolean
    skipSslVerification?: boolean
}

export async function resolveCatalog(runtime: Runtime, options: CatalogOptions): Promise<ResolvedCatalog> {
    const bundled = (reasonCode: BundledReason, reason: string, previous?: CatalogEnvelope): ResolvedCatalog => ({
        origin: 'bundled',
        catalog: undefined,
        fetchedAt: null,
        reason,
        reasonCode,
        previous,
        retryAfter: null,
        downloadSkipped: false,
    })

    if (runtime.env.HOG_API_CATALOG === 'bundled') {
        return bundled('pinned', 'HOG_API_CATALOG is set to bundled')
    }
    if (options.skipSslVerification) {
        return bundled('insecure_tls', 'TLS verification is off')
    }

    let path: string
    try {
        path = hogFile(runtime, CACHE_FILE)
    } catch {
        return bundled('no_folder', 'hog has no folder to keep the catalog in')
    }
    const cache = await readCache(runtime, path)
    const key = hostKey(options.host)
    const entry = cache.hosts[key]
    const saved = entry?.catalog ?? undefined
    const save = (next: HostCache): Promise<void> =>
        writeCache(runtime, path, { hosts: { ...cache.hosts, [key]: next } })
    const adopt = (origin: CatalogOrigin, catalog: CatalogEnvelope, fetchedAt: number | null): ResolvedCatalog => {
        const reason = incompatibility(catalog)
        return reason
            ? { ...bundled('needs_newer_hog', reason, saved), fetchedAt }
            : {
                  origin,
                  catalog,
                  fetchedAt,
                  reason: null,
                  reasonCode: null,
                  previous: saved,
                  retryAfter: null,
                  downloadSkipped: false,
              }
    }
    const fallBack = (
        failure: string,
        notServed: boolean,
        retryAfter: number,
        downloadSkipped: boolean
    ): ResolvedCatalog => ({
        ...(saved
            ? adopt('cache', saved, entry?.fetchedAt ?? null)
            : bundled(notServed ? 'not_served' : 'unreachable', failure)),
        retryAfter,
        downloadSkipped,
    })

    if (!options.refresh && saved && entry?.fetchedAt != null && runtime.now() - entry.fetchedAt < DAY_MS) {
        return adopt('cache', saved, entry.fetchedAt)
    }
    if (!options.refresh && entry?.retryAfter != null && runtime.now() < entry.retryAfter) {
        return fallBack(
            entry.failure?.reason ?? 'the last download failed',
            entry.failure?.notServed ?? false,
            entry.retryAfter,
            true
        )
    }

    const result = await download(runtime, catalogUrl(options.host), saved ? (entry?.etag ?? null) : null)
    if (result.kind === 'catalog') {
        const fetchedAt = runtime.now()
        await save({ fetchedAt, etag: result.etag, catalog: result.catalog, retryAfter: null, failure: null })
        return adopt('network', result.catalog, fetchedAt)
    }
    if (result.kind === 'unchanged' && entry && saved) {
        const fetchedAt = runtime.now()
        await save({ ...entry, fetchedAt, retryAfter: null, failure: null })
        return adopt('network', saved, fetchedAt)
    }

    const failure = result.kind === 'failed' ? result.reason : `${new URL(options.host).origin} sent no catalog`
    const notServed = result.kind === 'failed' && result.notServed
    const retryAfter = runtime.now() + RETRY_AFTER_MS
    await save({
        fetchedAt: entry?.fetchedAt ?? null,
        etag: entry?.etag ?? null,
        catalog: entry?.catalog ?? null,
        retryAfter,
        failure: { reason: failure, notServed },
    })
    if (options.refresh && notServed) {
        return { ...bundled('not_served', failure, saved), retryAfter }
    }
    if (options.refresh) {
        throw new HogError(
            'catalog_unreachable',
            `hog couldn't download the API tool catalog: ${failure}.`,
            saved
                ? 'hog keeps using the catalog it has. Check your network connection, then run `hog api refresh` again.'
                : 'hog keeps using the tools built into it. Check your network connection, then run `hog api refresh` again.'
        )
    }
    return fallBack(failure, notServed, retryAfter, false)
}
