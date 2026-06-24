/** Scrubs PII out of CSS text and inline `style` values by redacting `url(...)` targets. */
import { ScrubContext } from './config'
import { ScrubResult } from './text'
import { scrubUrl } from './url'

const URL_FN_RE = /url\(\s*(['"]?)([^'")]*)\1\s*\)/gi

export function scrubCss(ctx: ScrubContext, css: string): ScrubResult {
    let changed = false
    const value = css.replace(URL_FN_RE, (match, quote: string, inner: string) => {
        // data-URIs and fragments carry no path PII; leave them (and empty url()) untouched.
        if (inner === '' || inner.startsWith('data:') || inner.startsWith('#')) {
            return match
        }
        const result = scrubUrl(ctx, inner)
        if (!result.changed) {
            return match
        }
        changed = true
        return `url(${quote}${result.value}${quote})`
    })
    return { changed, value }
}
