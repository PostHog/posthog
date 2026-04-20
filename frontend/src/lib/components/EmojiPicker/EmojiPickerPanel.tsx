import clsx from 'clsx'
import {
    EmojiPicker,
    EmojiPickerListCategoryHeaderProps,
    EmojiPickerListEmojiProps,
    EmojiPickerListRowProps,
} from 'frimousse'

const EmojiPickerCategoryHeader = ({ category, ...props }: EmojiPickerListCategoryHeaderProps): JSX.Element => (
    <div className="bg-bg-light px-3 pt-3 pb-1.5 font-medium text-neutral-600 text-sm" {...props}>
        {category.label}
    </div>
)

const EmojiPickerEmojiRow = ({ children, ...props }: EmojiPickerListRowProps): JSX.Element => (
    <div className="scroll-my-1.5 px-1.5" {...props}>
        {children}
    </div>
)

const EmojiPickerEmojiButton = ({ emoji, ...props }: EmojiPickerListEmojiProps): JSX.Element => (
    <button
        data-attr="emoji-picker-button"
        className="flex items-center justify-center rounded-md text-xl size-8 data-[active]:bg-secondary-3000-hover"
        {...props}
    >
        {emoji.emoji}
    </button>
)

export type EmojiPickerPanelProps = {
    /** Called with the selected emoji character */
    onEmojiSelect: (emoji: string) => void
    className?: string
}

/** Frimousse emoji grid + search (no trigger); use inside a Popover or other container */
export function EmojiPickerPanel({ onEmojiSelect, className }: EmojiPickerPanelProps): JSX.Element {
    return (
        <EmojiPicker.Root
            className={clsx('isolate flex h-[368px] w-fit flex-col bg-bg-light', className)}
            onEmojiSelect={({ emoji }) => {
                onEmojiSelect(emoji)
            }}
        >
            <EmojiPicker.Search className="z-10 mx-2 mt-2 appearance-none rounded bg-fill-input px-2.5 py-2 text-sm border" />
            <EmojiPicker.Viewport className="relative flex-1 outline-hidden">
                <EmojiPicker.Loading className="absolute inset-0 flex items-center justify-center text-tertiary text-sm">
                    Loading…
                </EmojiPicker.Loading>
                <EmojiPicker.Empty className="absolute inset-0 flex items-center justify-center text-tertiary text-sm">
                    No emoji found.
                </EmojiPicker.Empty>
                <EmojiPicker.List
                    className="select-none pb-1.5"
                    components={{
                        CategoryHeader: EmojiPickerCategoryHeader,
                        Row: EmojiPickerEmojiRow,
                        Emoji: EmojiPickerEmojiButton,
                    }}
                />
            </EmojiPicker.Viewport>
        </EmojiPicker.Root>
    )
}
