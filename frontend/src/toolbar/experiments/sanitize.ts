import DOMPurify, { type Config } from 'dompurify'

// Web-experiment transforms reach the page via innerHTML/style and are fetched
// against uiHost, which is launch-hash-influenceable — sanitize at the sink.

// USE_PROFILES is the primary allowlist; FORBID_* below are defense-in-depth in case
// the profile is later changed. `style` is forbidden both as tag and attribute so that
// CSS exfil channels can't slip through inside HTML payloads — legitimate CSS belongs
// in transform.css, which goes through sanitizeExperimentStyle.
const HTML_CONFIG: Config = {
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'form', 'link', 'meta', 'base', 'style'],
    FORBID_ATTR: ['srcdoc', 'formaction', 'style'],
    USE_PROFILES: { html: true },
}

export function sanitizeExperimentHTML(html: string | undefined | null): string {
    if (!html) {
        return ''
    }
    return DOMPurify.sanitize(html, HTML_CONFIG)
}

// url() is the only meaningful exfil channel on inline styles (background-image,
// cursor, mask-image, list-style-image, border-image). Houdini paint() and the
// image-set/cross-fade families also resolve to URL fetches. @import and expression()
// are unreachable from inline `style=""` attributes but kept as belt-and-suspenders.
const CSS_FETCH_FUNCTIONS = /url\s*\(|image-set\s*\(|cross-fade\s*\(|paint\s*\(|expression\s*\(/i

export function sanitizeExperimentStyle(css: string | undefined | null): string {
    if (!css) {
        return ''
    }
    if (!CSS_FETCH_FUNCTIONS.test(css)) {
        return css
    }
    // Risky pattern in the raw input. Rebuild from only declarations the browser parsed
    // AND that don't match the filter — anything the parser couldn't classify is dropped,
    // so newer fetching syntaxes the runtime doesn't recognize fail closed.
    const probe = document.createElement('div')
    probe.setAttribute('style', css)
    const safe = document.createElement('div')
    for (let i = 0; i < probe.style.length; i++) {
        const prop = probe.style[i]
        const value = probe.style.getPropertyValue(prop)
        if (!CSS_FETCH_FUNCTIONS.test(value)) {
            safe.style.setProperty(prop, value)
        }
    }
    return safe.getAttribute('style') || ''
}

export function setSanitizedHTML(el: Element, html: string | undefined | null): void {
    el.innerHTML = sanitizeExperimentHTML(html)
}

export function setSanitizedStyle(el: Element, css: string | undefined | null): void {
    const sanitized = sanitizeExperimentStyle(css)
    if (sanitized) {
        el.setAttribute('style', sanitized)
    } else {
        el.removeAttribute('style')
    }
}

// Predicate helpers for UI affordances. String equality on the sanitized output
// over-triggers because the browser normalizes CSS whitespace and case during
// the setAttribute/getAttribute round-trip.

export function htmlSanitizationWouldStrip(html: string | undefined | null): boolean {
    if (!html) {
        return false
    }
    return sanitizeExperimentHTML(html).length < html.length
}

export function styleSanitizationWouldStrip(css: string | undefined | null): boolean {
    return !!css && CSS_FETCH_FUNCTIONS.test(css)
}
