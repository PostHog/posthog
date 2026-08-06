import { useValues } from 'kea'

import { businessKnowledgeLogic } from '../scenes/businessKnowledgeLogic'

export function CrawlModeHelp(): JSX.Element {
    const { urlSource } = useValues(businessKnowledgeLogic)
    if (urlSource.crawl_mode === 'single') {
        return (
            <p className="text-xs text-muted">
                Fetch this URL once and index its main text. Use the refresh button on the row to re-fetch.
            </p>
        )
    }
    if (urlSource.crawl_mode === 'sitemap') {
        return (
            <p className="text-xs text-muted">
                Read sitemap.xml at this URL (or <code>/sitemap.xml</code> at its origin) and index each listed page.
                Scheduled refresh is Stage 5.
            </p>
        )
    }
    return (
        <p className="text-xs text-muted">
            Indexes this page and everything under its path on the same site. Use "Skip paths" to carve out sections you
            don't want; depth and max pages bound the crawl. Honors robots.txt.
        </p>
    )
}
