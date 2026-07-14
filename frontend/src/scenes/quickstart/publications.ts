export interface QuickstartPublication {
    title: string
    url: string
    description: string
    publishedAt: string
    author?: string
    imageUrl?: string
}

export const QUICKSTART_PUBLICATIONS_PAGE_SIZE = 8

const RSS_URL = 'https://posthog.com/rss.xml'
const CACHE_KEY = 'ph-quickstart-publications'
const CACHE_TTL_MS = 6 * 60 * 60 * 1000
// The feed embeds full post bodies, so reading it whole costs several MB. Items are newest
// first: the response is streamed and more bytes are pulled only as the user scrolls deeper.
// The cap is a runaway guard sitting above the full feed size.
const MAX_FEED_CHARS = 8 * 1024 * 1024

export interface PublicationsPage {
    publications: QuickstartPublication[]
    hasMore: boolean
}

interface PublicationsCache {
    fetchedAt: number
    publications: QuickstartPublication[]
}

const readCache = (): QuickstartPublication[] | null => {
    try {
        const raw = window.localStorage.getItem(CACHE_KEY)
        if (!raw) {
            return null
        }
        const cache = JSON.parse(raw) as PublicationsCache
        if (!Array.isArray(cache.publications) || Date.now() - cache.fetchedAt > CACHE_TTL_MS) {
            return null
        }
        return cache.publications
    } catch {
        return null
    }
}

const writeCache = (publications: QuickstartPublication[]): void => {
    try {
        window.localStorage.setItem(CACHE_KEY, JSON.stringify({ fetchedAt: Date.now(), publications }))
    } catch {
        // Storage unavailable or full. Caching is best-effort.
    }
}

// The feed glues the site origin onto already-absolute CDN image URLs
const fixImageUrl = (url: string | null): string | undefined =>
    url ? url.replace(/^https:\/\/posthog\.com(?=https?:\/\/)/, '') : undefined

const countItems = (xml: string): number => xml.split('</item>').length - 1

const textOf = (item: Element, tag: string): string => item.getElementsByTagName(tag)[0]?.textContent?.trim() ?? ''

export function parsePublicationsRss(xml: string, limit: number): QuickstartPublication[] {
    // A partial download usually cuts off mid-item: keep only complete items and
    // re-close the document so DOMParser accepts it.
    const lastItemEnd = xml.lastIndexOf('</item>')
    if (lastItemEnd === -1) {
        return []
    }
    const doc = new DOMParser().parseFromString(
        xml.slice(0, lastItemEnd + '</item>'.length) + '</channel></rss>',
        'text/xml'
    )
    return Array.from(doc.getElementsByTagName('item'))
        .slice(0, limit)
        .map((item) => ({
            title: textOf(item, 'title'),
            url: textOf(item, 'link'),
            description: textOf(item, 'description'),
            publishedAt: textOf(item, 'pubDate'),
            author: textOf(item, 'dc:creator') || undefined,
            imageUrl: fixImageUrl(item.getElementsByTagName('enclosure')[0]?.getAttribute('url') ?? null),
        }))
        .filter((publication) => publication.title && publication.url)
}

/**
 * Lazily consumes the RSS response across pages: each ensureItems call reads just enough
 * additional bytes for the requested number of items, so scrolling the feed streams the
 * download instead of fetching megabytes upfront.
 */
class FeedStream {
    private reader: ReadableStreamDefaultReader<Uint8Array> | null = null
    private decoder = new TextDecoder()
    private xml = ''
    private exhausted = false
    private started = false

    private async start(): Promise<void> {
        this.started = true
        const response = await fetch(RSS_URL)
        if (!response.ok) {
            this.exhausted = true
            throw new Error(`Failed to load the PostHog RSS feed: ${response.status}`)
        }
        if (response.body) {
            this.reader = response.body.getReader()
        } else {
            this.xml = await response.text()
            this.exhausted = true
        }
    }

    async ensureItems(count: number): Promise<{ xml: string; exhausted: boolean }> {
        if (!this.started) {
            await this.start()
        }
        while (this.reader && !this.exhausted && countItems(this.xml) < count) {
            if (this.xml.length >= MAX_FEED_CHARS) {
                this.exhausted = true
                break
            }
            const { done, value } = await this.reader.read()
            if (done) {
                this.exhausted = true
                break
            }
            this.xml += this.decoder.decode(value, { stream: true })
        }
        return { xml: this.xml, exhausted: this.exhausted }
    }
}

let feedStream: FeedStream | null = null

/** Load one page of the feed. The first page may be served from the local cache. */
export async function fetchPublicationsPage(offset: number): Promise<PublicationsPage> {
    if (offset === 0) {
        const cached = readCache()
        if (cached) {
            return { publications: cached, hasMore: true }
        }
    }
    if (!feedStream) {
        feedStream = new FeedStream()
    }
    let xml: string
    let exhausted: boolean
    try {
        ;({ xml, exhausted } = await feedStream.ensureItems(offset + QUICKSTART_PUBLICATIONS_PAGE_SIZE))
    } catch (error) {
        // A failed stream can't be resumed. The next call starts fresh.
        feedStream = null
        throw error
    }
    const parsed = parsePublicationsRss(xml, offset + QUICKSTART_PUBLICATIONS_PAGE_SIZE)
    const publications = parsed.slice(offset)
    const hasMore = !exhausted || countItems(xml) > offset + QUICKSTART_PUBLICATIONS_PAGE_SIZE
    if (offset === 0 && publications.length > 0) {
        writeCache(publications)
    }
    return { publications, hasMore }
}
