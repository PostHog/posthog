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
// image-set / cross-fade / -webkit-image-set families also resolve to URL fetches.
const CSS_FETCH_FUNCTIONS = /url\s*\(|image-set\s*\(|-webkit-image-set\s*\(|cross-fade\s*\(|paint\s*\(|expression\s*\(/i

export function sanitizeExperimentStyle(css: string | undefined | null): string {
    if (!css) {
        return ''
    }
    // Always normalize through CSSOM and test the parsed value. A raw-string check
    // would miss CSS character escapes like `ur\l(...)` and vendor-prefixed wrappers
    // that don't embed `url(` — the browser resolves both into a real url() fetch.
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
    if (!css) {
        return false
    }
    // Compare property counts on the normalized form so CSS escapes / vendor wrappers
    // are correctly flagged. Whitespace-only and string-shape differences don't trip it.
    const probe = document.createElement('div')
    probe.setAttribute('style', css)
    const before = probe.style.length
    let after = 0
    for (let i = 0; i < probe.style.length; i++) {
        if (!CSS_FETCH_FUNCTIONS.test(probe.style.getPropertyValue(probe.style[i]))) {
            after++
        }
    }
    return after < before
}
