import {
    EmojiPicker,
    EmojiPickerListCategoryHeaderProps,
    EmojiPickerListEmojiProps,
    EmojiPickerListRowProps,
} from 'frimousse'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'
import { useState } from 'react'
import { IconEmojiAdd } from '@posthog/icons'

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

export interface EmojiPickerPopoverProps {
    /**
     * The action to take when a user selects an emoji
     * receives the emoji as a string
     */
    onSelect: (s: string) => void
    /**
     * Whether to start with the popover open or closed
     * Defaults to false (closed)
     */
    defaultOpen?: boolean
    /**
     * the data-attr to set on the button that opens and closes the popover
     */
    'data-attr'?: string
}

export function EmojiPickerPopover({
    onSelect,
    defaultOpen = false,
    'data-attr': dataAttr,
}: EmojiPickerPopoverProps): JSX.Element {
    const [emojiPickerOpen, setEmojiPickerOpen] = useState(defaultOpen)

    return (
        <Popover
            onClickOutside={() => setEmojiPickerOpen(false)}
            // prefer the bottom, but will fall back to other positions based on space
            placement="bottom-start"
            visible={emojiPickerOpen}
            overlay={
                <EmojiPicker.Root
                    className="isolate flex h-[368px] w-fit flex-col bg-bg-light"
                    onEmojiSelect={({ emoji }) => {
                        onSelect(emoji)
                        setEmojiPickerOpen(false)
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
            }
        >
            <LemonButton
                data-attr={dataAttr}
                icon={<IconEmojiAdd className="text-lg" />}
                onClick={() => {
                    setEmojiPickerOpen(!emojiPickerOpen)
                }}
                size="small"
            />
        </Popover>
    )
}
