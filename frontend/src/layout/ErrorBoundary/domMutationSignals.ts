export type ExceptionProperties = Record<string, number | string | boolean | bigint | symbol | null | undefined>

const DOM_MUTATION_PATTERNS = [
    "Failed to execute 'removeChild' on 'Node'",
    "Failed to execute 'insertBefore' on 'Node'",
    "Failed to execute 'appendChild' on 'Node'",
]

export function isDOMMutationError(error: unknown): boolean {
    const message = error instanceof Error ? error.message : typeof error === 'string' ? error : ''
    return DOM_MUTATION_PATTERNS.some((pattern) => message.includes(pattern))
}

// Anything that rewrites our text nodes in place leaves a fingerprint. Chrome and Edge translate a
// page by wrapping every translated run in a <font> element, and that swap is what desyncs React.
// The app itself never renders one, so any <font> in the document came from outside.
function countInjectedFontElements(): number {
    return document.getElementsByTagName('font').length
}

function collectTranslationHints(fontElementCount: number): string[] {
    const hints: string[] = []
    const { classList } = document.documentElement
    if (classList.contains('translated-ltr') || classList.contains('translated-rtl')) {
        hints.push('translated_html_class')
    }
    if (fontElementCount > 0) {
        hints.push('font_wrapped_text')
    }
    if (document.querySelector('[_msttexthash], [_mstmutation]')) {
        hints.push('microsoft_translator')
    }
    if (document.querySelector('.goog-te-banner-frame, #goog-gt-tt, .skiptranslate')) {
        hints.push('google_translate_widget')
    }
    return hints
}

/**
 * Locale and page-rewriting signals for the `removeChild`/`insertBefore` family of React crashes
 * (react#11538). Page-translation extensions cause the overwhelming majority of them, but genuine
 * in-app desyncs throw the identical message, so without these properties the real bugs are
 * indistinguishable from extension noise in error tracking.
 *
 * Returns nothing for any other error, and must be called at capture time: whether the page has
 * been translated is only knowable once the crash has happened.
 */
export function getDOMMutationSignals(error: unknown): ExceptionProperties {
    if (!isDOMMutationError(error)) {
        return {}
    }
    try {
        const fontElementCount = countInjectedFontElements()
        const hints = collectTranslationHints(fontElementCount)
        return {
            dom_mutation_error: true,
            page_translated: hints.length > 0,
            page_translation_hints: hints.join(','),
            injected_font_element_count: fontElementCount,
            browser_language: navigator.language,
            browser_languages: navigator.languages?.join(',') ?? '',
            document_language: document.documentElement.lang,
        }
    } catch {
        // We're already inside error handling, so a probe that throws must not replace the crash.
        return { dom_mutation_error: true }
    }
}
