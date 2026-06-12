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
            BFS-crawl from this URL staying on the same scheme + host + port. Honors robots.txt.
        </p>
    )
}
