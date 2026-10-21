import { querySelectorAllDeep } from 'query-selector-shadow-dom'
import { createContext } from 'react'

export interface SelectorMatchCounter {
    /** `undefined` while the count is pending, `null` for an invalid selector. */
    count: (selector: string) => number | null | undefined
    request: (selector: string) => void
}

/** Counts in the document the component renders in, which is the page for the floating toolbar. */
const pageDocumentCounter: SelectorMatchCounter = {
    count: (selector) => {
        try {
            return querySelectorAllDeep(selector).length
        } catch {
            return null
        }
    },
    request: () => {},
}

// The extension side panel renders the editors in its own page, so it provides a counter for the customer's page.
export const SelectorCountContext = createContext<SelectorMatchCounter>(pageDocumentCounter)
