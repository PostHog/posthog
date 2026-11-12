import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseJsonOrUndefined } from '@/core/json'
import { hogFile } from '@/core/paths'
import type { Runtime } from '@/core/runtime'
import { VERSION } from '@/version'

import { type Host, regionOf } from './host'

export const CATALOG_URL = 'https://mcp.posthog.com/cli/catalog.json'

const CACHE_FILE = 'api-catalog.json'
const DAY_MS = 24 * 60 * 60 * 1000
const FETCH_TIMEOUT_MS = 5000

const CatalogEnvelopeSchema = z.object({
    schemaVersion: z.number().int(),
    minHogVersion: z.string(),
    build: z.string().nullable(),
    tools: z.array(z.unknown()),
})

type CatalogEnvelope = z.output<typeof CatalogEnvelopeSchema>

const CacheSchema = z.object({
    fetchedAt: z.number(),
    etag: z.string().nullable(),
    catalog: CatalogEnvelopeSchema,
})

type Cache = z.output<typeof CacheSchema>

export type CatalogOrigin = 'network' | 'cache' | 'bundled'

export type BundledReason = 'pinned' | 'self_hosted' | 'needs_newer_hog' | 'no_folder' | 'unreachable'

export interface ResolvedCatalog {
    origin: CatalogOrigin
    catalog: CatalogEnvelope | undefined
    fetchedAt: number | null
    reason: string | null
    reasonCode: BundledReason | null
    previous: CatalogEnvelope | undefined
}

function parseVersion(version: string): { core: number[]; pre: string[] } | undefined {
    const match = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+.*)?$/.exec(version)
    if (!match) {
        return undefined
    }
    return { core: [Number(match[1]), Number(match[2]), Number(match[3])], pre: match[4] ? match[4].split('.') : [] }
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
        const numeric = /^\d+$/.test(x) && /^\d+$/.test(y)
        const difference = numeric ? Number(x) - Number(y) : x.localeCompare(y)
        if (difference !== 0) {
            return Math.sign(difference)
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

async function readCache(runtime: Runtime, path: string): Promise<Cache | undefined> {
    try {
        return parseJsonOrUndefined(await runtime.readFile(path), CacheSchema)
    } catch {
        return undefined
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
    | { kind: 'failed'; reason: string }

async function download(runtime: Runtime, etag: string | null): Promise<Download> {
    try {
        const response = await runtime.fetch(CATALOG_URL, {
            headers: etag ? { 'If-None-Match': etag } : {},
            timeoutMs: FETCH_TIMEOUT_MS,
            skipRateLimit: true,
        })
        if (response.status === 304) {
            return { kind: 'unchanged' }
        }
        if (!response.ok) {
            return { kind: 'failed', reason: `the MCP server answered ${response.status}` }
        }
        const catalog = parseJsonOrUndefined(await response.text(), CatalogEnvelopeSchema)
        if (!catalog) {
            return { kind: 'failed', reason: 'the MCP server sent a catalog hog could not read' }
        }
        return { kind: 'catalog', catalog, etag: response.headers.get('ETag') }
    } catch (error) {
        return { kind: 'failed', reason: error instanceof Error ? error.message : String(error) }
    }
}

export interface CatalogOptions {
    host: Host | undefined
    refresh?: boolean
}

export async function resolveCatalog(runtime: Runtime, options: CatalogOptions): Promise<ResolvedCatalog> {
    const bundled = (reasonCode: BundledReason, reason: string, previous?: CatalogEnvelope): ResolvedCatalog => ({
        origin: 'bundled',
        catalog: undefined,
        fetchedAt: null,
        reason,
        reasonCode,
        previous,
    })

    if (runtime.env.HOG_API_CATALOG === 'bundled') {
        return bundled('pinned', 'HOG_API_CATALOG is set to bundled')
    }
    if (options.host !== undefined && regionOf(options.host) === undefined) {
        return bundled('self_hosted', 'the tool catalog describes PostHog Cloud, and this host is self-hosted')
    }

    let path: string
    try {
        path = hogFile(runtime, CACHE_FILE)
    } catch {
        return bundled('no_folder', 'hog has no folder to keep the catalog in')
    }
    const cache = await readCache(runtime, path)
    const adopt = (origin: CatalogOrigin, catalog: CatalogEnvelope, fetchedAt: number): ResolvedCatalog => {
        const reason = incompatibility(catalog)
        return reason
            ? { ...bundled('needs_newer_hog', reason, cache?.catalog), fetchedAt }
            : { origin, catalog, fetchedAt, reason: null, reasonCode: null, previous: cache?.catalog }
    }

    if (cache && !options.refresh && runtime.now() - cache.fetchedAt < DAY_MS) {
        return adopt('cache', cache.catalog, cache.fetchedAt)
    }

    const result = await download(runtime, cache?.etag ?? null)
    if (result.kind === 'catalog') {
        const fetchedAt = runtime.now()
        await writeCache(runtime, path, { fetchedAt, etag: result.etag, catalog: result.catalog })
        return adopt('network', result.catalog, fetchedAt)
    }
    if (result.kind === 'unchanged' && cache) {
        const fetchedAt = runtime.now()
        await writeCache(runtime, path, { ...cache, fetchedAt })
        return adopt('network', cache.catalog, fetchedAt)
    }
    if (options.refresh) {
        throw new HogError(
            'catalog_unreachable',
            `hog couldn't download the API tool catalog: ${result.kind === 'failed' ? result.reason : 'the MCP server sent no catalog'}.`,
            cache
                ? 'hog keeps using the catalog it has. Check your network connection, then run `hog api refresh` again.'
                : 'hog keeps using the tools built into it. Check your network connection, then run `hog api refresh` again.'
        )
    }
    return cache
        ? adopt('cache', cache.catalog, cache.fetchedAt)
        : bundled('unreachable', "the catalog couldn't be downloaded")
}
