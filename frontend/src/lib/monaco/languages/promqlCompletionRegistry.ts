export interface PromQLCompletionItem {
    label: string
    insertText: string
    kind: 'function' | 'aggregation' | 'metric' | 'label' | 'value' | 'duration' | 'keyword'
    detail?: string
    documentation?: string
    /** `insertText` is a snippet (it has a `$0` cursor stop). */
    snippet?: boolean
    /** Open the suggestions again after the insert, as for a label name that needs a value next. */
    retrigger?: boolean
    sortText?: string
}

/** Suggestions for the text at `offset`, and the offset where the replaced word starts. */
export type PromQLCompletionProvider = (
    text: string,
    offset: number
) => Promise<{ from: number; items: PromQLCompletionItem[]; incomplete: boolean } | null>

// Each mounted editor that owns the data (a product, with its own API) adds one; the language stays
// generic. The newest one answers, and removing it gives the next editor its suggestions back.
const completionProviders: PromQLCompletionProvider[] = []

/** Adds a source of PromQL suggestions. Returns a function that removes it again. */
export function setPromQLCompletionProvider(provider: PromQLCompletionProvider): () => void {
    completionProviders.push(provider)
    return () => {
        const index = completionProviders.lastIndexOf(provider)
        if (index !== -1) {
            completionProviders.splice(index, 1)
        }
    }
}

export function getPromQLCompletionProvider(): PromQLCompletionProvider | null {
    return completionProviders[completionProviders.length - 1] ?? null
}
