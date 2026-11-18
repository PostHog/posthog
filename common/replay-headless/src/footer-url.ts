/** Drop the query string, which often runs to hundreds of characters of tracking and state parameters. */
export function footerUrl(href: string): string {
    try {
        const url = new URL(href)
        url.search = ''
        return url.toString()
    } catch {
        const hashAt = href.indexOf('#')
        const queryAt = href.indexOf('?')
        if (queryAt === -1 || (hashAt !== -1 && hashAt < queryAt)) {
            return href
        }
        return href.slice(0, queryAt) + (hashAt === -1 ? '' : href.slice(hashAt))
    }
}
