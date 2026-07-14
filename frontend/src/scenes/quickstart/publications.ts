export interface QuickstartPublication {
    title: string
    url: string
    description: string
    publishedAt: string
    author?: string
    imageUrl?: string
}

const RSS_URL = 'https://posthog.com/rss.xml'
const CACHE_KEY = 'ph-quickstart-publications'
const CACHE_TTL_MS = 6 * 60 * 60 * 1000
// The feed is several MB because items embed full post bodies. The newest items sit at
// the top, so we stream the response and cancel once we have what we need, capped as a
// safety net in case the feed shape changes.
const MAX_FEED_CHARS = 512 * 1024

export const QUICKSTART_PUBLICATION_COUNT = 4

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
        // Storage unavailable or full - caching is best-effort
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

async function readFeedHead(response: Response): Promise<string> {
    const reader = response.body?.getReader()
    if (!reader) {
        return await response.text()
    }
    const decoder = new TextDecoder()
    let xml = ''
    while (xml.length < MAX_FEED_CHARS && countItems(xml) <= QUICKSTART_PUBLICATION_COUNT) {
        const { done, value } = await reader.read()
        if (done) {
            break
        }
        xml += decoder.decode(value, { stream: true })
    }
    void reader.cancel().catch(() => {})
    return xml
}

export async function fetchQuickstartPublications(): Promise<QuickstartPublication[]> {
    const cached = readCache()
    if (cached) {
        return cached
    }
    const response = await fetch(RSS_URL)
    if (!response.ok) {
        throw new Error(`Failed to load the PostHog RSS feed: ${response.status}`)
    }
    const publications = parsePublicationsRss(await readFeedHead(response), QUICKSTART_PUBLICATION_COUNT)
    if (publications.length > 0) {
        writeCache(publications)
    }
    return publications
}
