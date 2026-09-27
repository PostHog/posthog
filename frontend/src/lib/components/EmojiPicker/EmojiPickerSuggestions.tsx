import { useActions, useValues } from 'kea'
import { useLayoutEffect } from 'react'

import { emojiSuggestionsLogic } from './emojiSuggestionsLogic'
import { RelatedEmojiButtons } from './RelatedEmojiButtons'

type EmojiPickerSuggestionsProps = {
    pickerKey: string
    query: string
    onEmojiSelect: (emoji: string) => void
}

export function EmojiPickerSuggestions({ pickerKey, query, onEmojiSelect }: EmojiPickerSuggestionsProps): JSX.Element {
    const logic = emojiSuggestionsLogic({ pickerKey })
    const { isSearchable, loading, suggestions } = useValues(logic)
    const { setQuery } = useActions(logic)
    // Before paint, so the previous query's result never flashes. The cleanup cancels a pending debounce.
    useLayoutEffect(() => {
        setQuery(query)
        return () => setQuery('')
    }, [query, setQuery])

    if (!isSearchable) {
        return <span>No emoji found.</span>
    }
    if (loading) {
        return <span>Finding related emojis…</span>
    }
    if (suggestions.length === 0) {
        return <span>No emoji found.</span>
    }
    return <RelatedEmojiButtons suggestions={suggestions} onEmojiSelect={onEmojiSelect} />
}
