import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { projectLogic } from 'scenes/projectLogic'

import { emojiSuggestionsLogic } from './emojiSuggestionsLogic'
import { RelatedEmojiButtons } from './RelatedEmojiButtons'

type EmojiPickerSuggestionsProps = {
    query: string
    onEmojiSelect: (emoji: string) => void
}

function SuggestedEmojis({
    query,
    projectId,
    onEmojiSelect,
}: EmojiPickerSuggestionsProps & { projectId: number }): JSX.Element {
    const { suggestions, loading } = useValues(emojiSuggestionsLogic({ query, projectId }))

    if (loading) {
        return <span>Finding related emojis…</span>
    }
    if (suggestions.length === 0) {
        return <span>No emoji found.</span>
    }
    return <RelatedEmojiButtons suggestions={suggestions} onEmojiSelect={onEmojiSelect} />
}

export function EmojiPickerSuggestions({ query, onEmojiSelect }: EmojiPickerSuggestionsProps): JSX.Element {
    const { currentProjectId } = useValues(projectLogic)
    const trimmedQuery = query.trim()
    const [debouncedQuery, setDebouncedQuery] = useState('')
    useEffect(() => {
        const timeout = window.setTimeout(() => setDebouncedQuery(trimmedQuery), 200)
        return () => window.clearTimeout(timeout)
    }, [trimmedQuery])
    const queryLength = [...trimmedQuery].length
    if (queryLength < 3 || queryLength > 64 || !currentProjectId) {
        return <span>No emoji found.</span>
    }
    if (debouncedQuery !== trimmedQuery) {
        return <span>Finding related emojis…</span>
    }
    return <SuggestedEmojis query={debouncedQuery} projectId={currentProjectId} onEmojiSelect={onEmojiSelect} />
}
