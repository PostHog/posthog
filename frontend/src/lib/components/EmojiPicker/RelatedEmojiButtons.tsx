import { EmojiSuggestionApi } from '~/generated/core/api.schemas'

export type RelatedEmojiButtonsProps = {
    suggestions: EmojiSuggestionApi[]
    onEmojiSelect: (emoji: string) => void
}

const ARROW_DIRECTION_MAP: Record<string, number> = {
    ArrowRight: 1,
    ArrowDown: 1,
    ArrowLeft: -1,
    ArrowUp: -1,
}

export function RelatedEmojiButtons({ suggestions, onEmojiSelect }: RelatedEmojiButtonsProps): JSX.Element {
    return (
        <span className="flex flex-col items-center gap-2">
            <span>Related emojis</span>
            <span className="flex gap-1">
                {suggestions.map(({ emoji, label }, index) => (
                    <button
                        type="button"
                        key={emoji}
                        data-attr="emoji-picker-related-button"
                        aria-label={label}
                        className="flex size-9 items-center justify-center rounded-md text-xl hover:bg-secondary-3000-hover focus-visible:bg-secondary-3000-hover"
                        onClick={() => onEmojiSelect(emoji)}
                        onKeyDown={(event) => {
                            const direction = ARROW_DIRECTION_MAP[event.key] ?? 0
                            if (direction) {
                                event.preventDefault()
                                const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                                    '[data-attr="emoji-picker-related-button"]'
                                )
                                buttons?.[(index + direction + suggestions.length) % suggestions.length]?.focus()
                            }
                        }}
                    >
                        {emoji}
                    </button>
                ))}
            </span>
        </span>
    )
}
