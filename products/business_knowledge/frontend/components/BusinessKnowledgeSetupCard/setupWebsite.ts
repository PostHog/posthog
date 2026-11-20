const NON_PUBLIC_SUFFIXES = ['.local', '.localhost', '.test', '.internal', '.invalid', '.example']
const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/

function isPublicHostname(hostname: string): boolean {
    // A hostname with no dot is `localhost` or a machine name, which the crawler cannot reach.
    if (!hostname.includes('.') || IPV4.test(hostname) || hostname.includes(':')) {
        return false
    }
    return !NON_PUBLIC_SUFFIXES.some((suffix) => hostname.endsWith(suffix))
}

export function pickWebsiteFromHosts(hosts: string[]): string | null {
    for (const host of hosts) {
        const hostname = host.trim().toLowerCase().replace(/:\d+$/, '')
        if (isPublicHostname(hostname)) {
            return `https://${hostname}`
        }
    }
    return null
}

export function normalizeWebsiteUrl(raw: string): string {
    const trimmed = raw.trim()
    if (!trimmed || /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)) {
        return trimmed
    }
    return `https://${trimmed}`
}

export function websiteSourceName(url: string): string | null {
    try {
        return new URL(url).hostname.replace(/^www\./, '') || null
    } catch {
        return null
    }
}
