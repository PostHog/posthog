/** Blur inline `url(data:image/...;base64,...)` backgrounds in CSS */
import { BLANK_IMAGE_DATA_URI, blurImageDataUri } from './blur'
import { ScrubContext } from './config'

const URL_DATA_IMAGE_RE = /url\(\s*(['"]?)(data:image\/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+)\1\s*\)/gi

/**
 * Replace each inline data-image background in `container[key]` with a blank placeholder synchronously
 * (fail-safe), and queue a deferred blur that splices the blurred image back in. Returns whether it acted.
 */
export function scrubCssImages(ctx: ScrubContext, container: Record<string, unknown>, key: string): boolean {
    const css = container[key]
    if (typeof css !== 'string') {
        return false
    }
    let changed = false
    let n = 0
    const value = css.replace(URL_DATA_IMAGE_RE, (_match, quote: string, original: string) => {
        changed = true
        // A unique, valid stand-in (blank image + ignored fragment) so each deferred blur can splice
        // its own image back independently; on blur failure it just stays the blank.
        const placeholder = `${BLANK_IMAGE_DATA_URI}#a${n++}`
        ctx.blurJobs?.push(async () => {
            const blurred = await blurImageDataUri(original)
            const cur = container[key]
            if (typeof cur === 'string') {
                container[key] = cur.replace(placeholder, () => blurred ?? BLANK_IMAGE_DATA_URI)
            }
        })
        return `url(${quote}${placeholder}${quote})`
    })
    if (changed) {
        container[key] = value
    }
    return changed
}
