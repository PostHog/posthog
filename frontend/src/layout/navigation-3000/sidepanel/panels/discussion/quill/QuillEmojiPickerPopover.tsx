import { useState } from 'react'

import { IconEmojiAdd } from '@posthog/icons'
import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { EmojiPickerPanel } from 'lib/components/EmojiPicker/EmojiPickerPanel'

interface QuillEmojiPickerPopoverProps {
    onSelect: (emoji: string) => void
    /** The icon-only button that opens the picker, without children. It shows the emoji icon. */
    trigger: JSX.Element
}

export function QuillEmojiPickerPopover({ onSelect, trigger }: QuillEmojiPickerPopoverProps): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={trigger}>
                <IconEmojiAdd />
            </PopoverTrigger>
            <PopoverContent align="end" className="w-auto p-0">
                <EmojiPickerPanel
                    onEmojiSelect={(emoji) => {
                        onSelect(emoji)
                        setOpen(false)
                    }}
                />
            </PopoverContent>
        </Popover>
    )
}
