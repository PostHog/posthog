import { querySelectorAllDeep } from 'query-selector-shadow-dom'
import { createContext } from 'react'

/**
 * `deep` also matches inside shadow roots, like actions do. `document` matches only the document itself, like
 * posthog-js applies web experiments with `document.querySelectorAll`.
 */
export type SelectorScope = 'deep' | 'document'

export type SelectorMatchCounts = Record<SelectorScope, number>

export interface SelectorMatchCounter {
    /** `undefined` while the count is pending, `null` for an invalid selector. */
    count: (selector: string, scope?: SelectorScope) => number | null | undefined
    request: (selector: string) => void
}

function countInScope(selector: string, scope: SelectorScope): number {
    return scope === 'deep' ? querySelectorAllDeep(selector).length : document.querySelectorAll(selector).length
}

/** Counts in both scopes, or returns `null` for an invalid selector. */
export function countSelectorMatches(selector: string): SelectorMatchCounts | null {
    try {
        return { deep: countInScope(selector, 'deep'), document: countInScope(selector, 'document') }
    } catch {
        return null
    }
}

/** Counts in the document the component renders in, which is the page for the floating toolbar. */
const pageDocumentCounter: SelectorMatchCounter = {
    count: (selector, scope = 'deep') => {
        try {
            return countInScope(selector, scope)
        } catch {
            return null
        }
    },
    request: () => {},
}

// The extension side panel renders the editors in its own page, so it provides a counter for the customer's page.
export const SelectorCountContext = createContext<SelectorMatchCounter>(pageDocumentCounter)
