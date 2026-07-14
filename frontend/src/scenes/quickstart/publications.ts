export interface QuickstartPublication {
    title: string
    url: string
    description: string
    publishedAt: string
    author?: string
    imageUrl?: string
}

export type PublicationFeedKey = 'blog' | 'newsletter'

export const QUICKSTART_PUBLICATIONS_PAGE_SIZE = 8
export const QUICKSTART_BLOG_URL = 'https://posthog.com/blog'
export const QUICKSTART_NEWSLETTER_URL = 'https://newsletter.posthog.com'

const BLOG_RSS_URL = 'https://posthog.com/rss.xml'
// Versioned: caches written by earlier revisions held fewer items than a full
// page and must not be served as page one of the feed
const BLOG_CACHE_KEY = 'ph-quickstart-publications-v4-blog'
const CACHE_TTL_MS = 6 * 60 * 60 * 1000
// The blog feed embeds full post bodies, so reading it whole costs several MB. Items are
// newest first: the response is streamed and more bytes are pulled only as the user scrolls
// deeper. The cap is a runaway guard sitting above the full feed size.
const MAX_FEED_CHARS = 8 * 1024 * 1024

export interface PublicationsPage {
    publications: QuickstartPublication[]
    hasMore: boolean
}

interface PublicationsCache {
    fetchedAt: number
    publications: QuickstartPublication[]
    hasMore: boolean
}

const readCache = (): PublicationsCache | null => {
    try {
        const raw = window.localStorage.getItem(BLOG_CACHE_KEY)
        if (!raw) {
            return null
        }
        const cache = JSON.parse(raw) as PublicationsCache
        if (
            !Array.isArray(cache.publications) ||
            // A short first page is only legitimate when the feed itself ended there
            (cache.publications.length < QUICKSTART_PUBLICATIONS_PAGE_SIZE && cache.hasMore !== false) ||
            Date.now() - cache.fetchedAt > CACHE_TTL_MS ||
            // A corrupted entry must fall through to a fresh fetch, not crash the render
            !cache.publications.every(
                (publication) =>
                    publication && typeof publication.title === 'string' && typeof publication.url === 'string'
            )
        ) {
            return null
        }
        return cache
    } catch {
        return null
    }
}

const writeCache = (publications: QuickstartPublication[], hasMore: boolean): void => {
    try {
        window.localStorage.setItem(BLOG_CACHE_KEY, JSON.stringify({ fetchedAt: Date.now(), publications, hasMore }))
    } catch {
        // Storage unavailable or full. Caching is best-effort.
    }
}

// The feed glues the site origin onto already-absolute CDN image URLs. Only https URLs
// survive: feed (and cached-feed) content must never inject another scheme into the DOM.
const fixImageUrl = (url: string | null): string | undefined => {
    const fixed = url?.replace(/^https:\/\/posthog\.com(?=https?:\/\/)/, '')
    return fixed?.startsWith('https://') ? fixed : undefined
}

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
        .filter((publication) => publication.title && publication.url.startsWith('https://'))
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
    // Tracked incrementally per chunk: recounting the whole buffer on every read is
    // quadratic over a multi-MB feed
    private itemCount = 0
    private exhausted = false
    private startPromise: Promise<void> | null = null
    // Serializes readers: the initial page load and the eager scroll sentinel can
    // overlap, and interleaved reader.read() calls would corrupt both results
    private pending: Promise<unknown> = Promise.resolve()

    private async start(): Promise<void> {
        const response = await fetch(BLOG_RSS_URL)
        if (!response.ok) {
            this.exhausted = true
            throw new Error(`Failed to load the PostHog RSS feed: ${response.status}`)
        }
        if (response.body) {
            this.reader = response.body.getReader()
        } else {
            this.xml = await response.text()
            this.itemCount = countItems(this.xml)
            this.exhausted = true
        }
    }

    async ensureItems(count: number): Promise<{ xml: string; exhausted: boolean }> {
        const run = this.pending.then(() => this.readUntil(count))
        this.pending = run.catch(() => undefined)
        return await run
    }

    private async readUntil(count: number): Promise<{ xml: string; exhausted: boolean }> {
        if (!this.startPromise) {
            this.startPromise = this.start()
        }
        await this.startPromise
        while (this.reader && !this.exhausted && this.itemCount < count) {
            if (this.xml.length >= MAX_FEED_CHARS) {
                this.exhausted = true
                break
            }
            const { done, value } = await this.reader.read()
            if (done) {
                this.exhausted = true
                break
            }
            const chunk = this.decoder.decode(value, { stream: true })
            // A closing tag can straddle the chunk boundary, so scan a tag-length tail with it
            // (the tail alone is too short to ever contain a full tag, so no double count)
            const tail = this.xml.slice(-('</item>'.length - 1))
            this.itemCount += countItems(tail + chunk)
            this.xml += chunk
        }
        return { xml: this.xml, exhausted: this.exhausted }
    }
}

let feedStream: FeedStream | null = null

async function fetchBlogPage(offset: number): Promise<PublicationsPage> {
    if (offset === 0) {
        const cached = readCache()
        if (cached) {
            return { publications: cached.publications, hasMore: cached.hasMore }
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
        writeCache(publications, hasMore)
    }
    return { publications, hasMore }
}

// Substack sends no CORS headers, so the newsletter feed can't be fetched from the
// browser. Until it's proxied server-side, the rail ships with a static seed of recent
// issues served through the same paging interface as the live blog feed.
const NEWSLETTER_ISSUES: QuickstartPublication[] = [
    {
        title: 'Product for Engineers is now build mode',
        url: 'https://newsletter.posthog.com/p/product-for-engineers-is-now-build',
        description: 'Same team, same posts. New brand, new focus.',
        publishedAt: 'Mon, 13 Jul 2026 18:39:17 GMT',
        author: 'Ian Vanagas',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/fd61ab64-b689-4d1e-b577-eb1849b29f0f_1456x1048.png',
    },
    {
        title: 'Stop being the code review bottleneck',
        url: 'https://newsletter.posthog.com/p/code-review-tips',
        description: '4 ways to make AI code review suck less (with prompts)',
        publishedAt: 'Thu, 09 Jul 2026 19:15:14 GMT',
        author: 'Jina Yoon',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/1018b66a-6d94-4190-b34b-60e0072e3840_1317x988.png',
    },
    {
        title: 'We used context engineering to 5x conversion and 2x activation',
        url: 'https://newsletter.posthog.com/p/we-used-ai-to-5x-conversion-and-2x',
        description: 'The magic behind our AI onboarding wizard',
        publishedAt: 'Wed, 24 Jun 2026 20:01:49 GMT',
        author: 'Edwin Lim',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/8b27cd51-6130-413b-bd94-a61af1985aa9_2912x2096.jpeg',
    },
    {
        title: "Why we're bullish on loops",
        url: 'https://newsletter.posthog.com/p/why-were-bullish-on-loops',
        description: 'WTF are loops, why is everyone arguing about them, and why do they actually matter?',
        publishedAt: 'Wed, 17 Jun 2026 17:48:56 GMT',
        author: 'Ian Vanagas',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/67da4d23-4902-4607-9536-1440c2fb5a8c_2912x2096.jpeg',
    },
    {
        title: "LLMs are picking winners. Here's how to become one",
        url: 'https://newsletter.posthog.com/p/llms-are-picking-winners-heres-how',
        description: "A startup's guide to answer engine optimization",
        publishedAt: 'Mon, 08 Jun 2026 18:11:58 GMT',
        author: 'Natalia Amorim',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/540f98b0-57fc-4156-99a6-b499d4736334_1569x1048.png',
    },
    {
        title: '24 tips for giving S-tier demos',
        url: 'https://newsletter.posthog.com/p/how-to-demo',
        description: "An engineer's guide to giving S-tier project demos",
        publishedAt: 'Thu, 28 May 2026 18:01:25 GMT',
        author: 'Jina Yoon',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/7b486099-4af3-4730-bd94-85219da88749_1456x1048.png',
    },
    {
        title: 'The stuff nobody tells you about startup marketing',
        url: 'https://newsletter.posthog.com/p/the-stuff-nobody-tells-you-about',
        description: 'Doing weird stuff on the internet is optional but recommended',
        publishedAt: 'Wed, 06 May 2026 18:01:37 GMT',
        author: 'Charles Cook',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/81aa278c-cc30-4ac1-b99c-c929bb846051_2912x2096.jpeg',
    },
    {
        title: 'Great companies are built in hackathons',
        url: 'https://newsletter.posthog.com/p/great-companies-are-built-in-hackathons',
        description: "You should run more hackathons. Here's how to do them well.",
        publishedAt: 'Tue, 21 Apr 2026 18:12:27 GMT',
        author: 'Ian Vanagas',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/7bf0320b-e7db-4bee-9814-0a38c84bb44c_2912x2096.jpeg',
    },
    {
        title: 'The golden rules of agent-first product engineering',
        url: 'https://newsletter.posthog.com/p/the-golden-rules-of-agent-first-product',
        description: 'Five principles to develop your product intuition for agents',
        publishedAt: 'Wed, 08 Apr 2026 19:01:23 GMT',
        author: 'Jina Yoon',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/29ab8f16-efac-4eaa-a09c-6124ef07b6de_2912x2096.jpeg',
    },
    {
        title: 'What we wish we knew about building AI agents',
        url: 'https://newsletter.posthog.com/p/what-we-wish-we-knew-before-building',
        description: 'Lessons learned from two years of building AI agents at PostHog',
        publishedAt: 'Tue, 24 Mar 2026 18:04:41 GMT',
        author: 'Ian Vanagas',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/c76757e8-e900-405e-b4a2-e97823ebf2f0_1456x1048.png',
    },
    {
        title: 'WTF does a product manager do? (and why engineers should care)',
        url: 'https://newsletter.posthog.com/p/an-engineers-guide-to-product-management',
        description: 'Skills for developers from the product manager playbook',
        publishedAt: 'Wed, 11 Mar 2026 21:11:01 GMT',
        author: 'Jina Yoon',
    },
    {
        title: 'The engineeringification of everything',
        url: 'https://newsletter.posthog.com/p/the-engineeringification-of-everything',
        description: 'Why every role seems like an engineering role now (and what it means for you)',
        publishedAt: 'Mon, 23 Feb 2026 19:04:07 GMT',
        author: 'Ian Vanagas',
        imageUrl:
            'https://substack-post-media.s3.amazonaws.com/public/images/b06de6cd-5664-4964-93ca-949d8a287664_3840x2742.png',
    },
]

function newsletterPage(offset: number): PublicationsPage {
    return {
        publications: NEWSLETTER_ISSUES.slice(offset, offset + QUICKSTART_PUBLICATIONS_PAGE_SIZE),
        hasMore: offset + QUICKSTART_PUBLICATIONS_PAGE_SIZE < NEWSLETTER_ISSUES.length,
    }
}

/** Load one page of a feed. The blog's first page may be served from the local cache. */
export async function fetchPublicationsPage(feed: PublicationFeedKey, offset: number): Promise<PublicationsPage> {
    if (feed === 'newsletter') {
        return newsletterPage(offset)
    }
    return await fetchBlogPage(offset)
}
