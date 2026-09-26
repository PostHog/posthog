import { EmojiSuggestionApi } from '~/generated/core/api.schemas'

export type RelatedEmojiButtonsProps = {
    suggestions: EmojiSuggestionApi[]
    onEmojiSelect: (emoji: string) => void
}

export function RelatedEmojiButtons({ suggestions, onEmojiSelect }: RelatedEmojiButtonsProps): JSX.Element {
    return (
        <span className="flex flex-col items-center gap-2">
            <span>Related emojis</span>
            <span className="flex gap-1">
                {suggestions.map(({ emoji, label }) => (
                    <button
                        type="button"
                        key={emoji}
                        data-attr="emoji-picker-related-button"
                        aria-label={label}
                        className="flex size-9 items-center justify-center rounded-md text-xl hover:bg-secondary-3000-hover focus-visible:bg-secondary-3000-hover"
                        onClick={() => onEmojiSelect(emoji)}
                    >
                        {emoji}
                    </button>
                ))}
            </span>
        </span>
    )
}
