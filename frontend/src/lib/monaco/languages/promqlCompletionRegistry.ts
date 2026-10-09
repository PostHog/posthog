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
) => Promise<{ from: number; items: PromQLCompletionItem[] } | null>

// The editor that owns the data (a product, with its own API) sets this; the language stays generic.
let completionProvider: PromQLCompletionProvider | null = null

/** Sets where PromQL suggestions come from. Returns a function that removes it again. */
export function setPromQLCompletionProvider(provider: PromQLCompletionProvider): () => void {
    completionProvider = provider
    return () => {
        if (completionProvider === provider) {
            completionProvider = null
        }
    }
}

export function getPromQLCompletionProvider(): PromQLCompletionProvider | null {
    return completionProvider
}
