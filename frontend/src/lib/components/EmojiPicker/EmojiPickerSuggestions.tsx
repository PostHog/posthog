import { useValues } from 'kea'

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
    if (query.trim().length < 3 || query.trim().length > 64 || !currentProjectId) {
        return <span>No emoji found.</span>
    }
    return <SuggestedEmojis query={query.trim()} projectId={currentProjectId} onEmojiSelect={onEmojiSelect} />
}
