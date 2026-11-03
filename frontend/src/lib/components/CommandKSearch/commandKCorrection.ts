export interface SearchCorrection {
    from: string
    to: string
}

/** The search to try when the typed text finds nothing: a pasted snake_case name split into words. */
export function correctedSearch(text: string): string | null {
    const split = text.replace(/_/g, ' ').replace(/\s+/g, ' ').trim()
    return split !== text && split ? split : null
}
