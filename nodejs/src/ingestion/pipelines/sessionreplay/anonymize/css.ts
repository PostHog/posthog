/** Blur inline `url(data:image/...;base64,...)` backgrounds in CSS */
import { BLANK_IMAGE_DATA_URI, blurImageDataUri, memoizedBlur } from './blur'
import { ScrubContext, isObject } from './config'

// rrweb inlines a same-origin/CORS-readable `<link rel="stylesheet">` into this attribute
// at snapshot time, so it holds full stylesheet text and needs the same CSS treatment as `style`.
export const INLINED_STYLESHEET_ATTR = '_cssText'

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
            const blurred = await memoizedBlur(ctx.blurCache, original, () => blurImageDataUri(original))
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

/** rrweb StyleSheetRule (source 8): CSS lives in `adds[].rule` and whole-sheet `replace`/`replaceSync`. */
export function scrubStyleSheetRule(ctx: ScrubContext, data: Record<string, unknown>): boolean {
    let changed = scrubCssImages(ctx, data, 'replace')
    changed = scrubCssImages(ctx, data, 'replaceSync') || changed
    return scrubRuleList(ctx, data.adds) || changed
}

/** rrweb StyleDeclaration (source 13): CSS value lives in `set.value`. */
export function scrubStyleDeclaration(ctx: ScrubContext, data: Record<string, unknown>): boolean {
    return isObject(data.set) ? scrubCssImages(ctx, data.set, 'value') : false
}

/** rrweb AdoptedStyleSheet (source 15): CSS lives in `styles[].rules[].rule`. */
export function scrubAdoptedStyleSheet(ctx: ScrubContext, data: Record<string, unknown>): boolean {
    if (!Array.isArray(data.styles)) {
        return false
    }
    let changed = false
    for (const style of data.styles) {
        if (isObject(style)) {
            changed = scrubRuleList(ctx, style.rules) || changed
        }
    }
    return changed
}

function scrubRuleList(ctx: ScrubContext, rules: unknown): boolean {
    if (!Array.isArray(rules)) {
        return false
    }
    let changed = false
    for (const rule of rules) {
        if (isObject(rule)) {
            changed = scrubCssImages(ctx, rule, 'rule') || changed
        }
    }
    return changed
}
