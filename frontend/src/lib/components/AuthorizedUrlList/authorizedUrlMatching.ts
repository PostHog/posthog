// Kept free of app imports so the toolbar browser extension can bundle it.

/**
 * Firefox does not allow you construct a new URL with e.g. https://*.example.com (which is to be fair more standards compliant than Chrome)
 * when used to probe for e.g. for authorized urls we only care if the proposed URL has a path so we can safely replace the wildcard with a character
 */
export function sanitizePossibleWildCardedURL(url: string): URL {
    const deWildCardedURL = url.replace(/\*/g, 'x')
    return new URL(deWildCardedURL)
}

/** Treat www.domain.com and domain.com as equivalent. */
const stripWww = (host: string): string => (host.startsWith('www.') ? host.slice(4) : host)

export const checkUrlIsAuthorized = (url: string | URL, authorizedUrls: string[]): boolean => {
    try {
        const parsedUrl = typeof url === 'string' ? sanitizePossibleWildCardedURL(url) : url
        const urlWithoutPath = parsedUrl.protocol + '//' + parsedUrl.host
        const hostNormalized = stripWww(parsedUrl.hostname)

        return authorizedUrls.some((authorizedUrl) => {
            // Wildcard entries (subdomain or port wildcards, e.g. `https://*.example.com`). Anchor the
            // pattern with ^…$ so a `*` cannot match a suffix of an unrelated origin such as
            // `https://app.example.com.evil.com`.
            if (authorizedUrl.includes('*')) {
                try {
                    const regex = new RegExp('^' + authorizedUrl.replace(/\./g, '\\.').replace(/\*/g, '.*') + '$')
                    return regex.test(urlWithoutPath)
                } catch {
                    return false
                }
            }

            // Exact entries: compare by origin (protocol + host) instead of a substring check, so a
            // different domain cannot be authorized merely by being a prefix/substring of an entry
            // (e.g. `https://example.co` against `https://example.com`).
            try {
                const authorizedUrlParsed = sanitizePossibleWildCardedURL(authorizedUrl)
                if (authorizedUrlParsed.protocol + '//' + authorizedUrlParsed.host === urlWithoutPath) {
                    return true
                }
                // www-equivalence: same protocol, hostnames equal with www. stripped. The protocol
                // check keeps an http origin from matching an https-only authorized entry.
                return (
                    authorizedUrlParsed.protocol === parsedUrl.protocol &&
                    stripWww(authorizedUrlParsed.hostname) === hostNormalized
                )
            } catch {
                return false
            }
        })
    } catch {
        // Ignore invalid URLs
    }

    return false
}
