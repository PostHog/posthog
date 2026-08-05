import { useState } from 'react'

import { IconEmojiAdd } from '@posthog/icons'

import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover'

import { EmojiPickerPanel } from './EmojiPickerPanel'

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
     * Size of the button that opens the popover
     * Defaults to 'small'
     */
    size?: LemonButtonProps['size']
    /**
     * the data-attr to set on the button that opens and closes the popover
     */
    'data-attr'?: string
}

export function EmojiPickerPopover({
    onSelect,
    defaultOpen = false,
    size = 'small',
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
                <EmojiPickerPanel
                    onEmojiSelect={(emoji) => {
                        onSelect(emoji)
                        setEmojiPickerOpen(false)
                    }}
                />
            }
        >
            <LemonButton
                data-attr={dataAttr}
                icon={<IconEmojiAdd />}
                onClick={() => {
                    setEmojiPickerOpen(!emojiPickerOpen)
                }}
                size={size}
            />
        </Popover>
    )
}
