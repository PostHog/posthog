import { osFrameSrc } from '../bridge/osFrame'

/** The frame `src` for an app link, or null when the link leaves this origin or does not parse. */
export function osAppSrc(href: string, origin: string): string | null {
    let url: URL
    try {
        url = new URL(href, origin)
    } catch {
        return null
    }
    if (url.origin !== new URL(origin).origin) {
        return null
    }
    return osFrameSrc(url, origin)
}
