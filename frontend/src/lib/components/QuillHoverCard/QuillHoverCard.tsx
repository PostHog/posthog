import { ComponentProps, ReactNode, SyntheticEvent } from 'react'

import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

// Hover cards sit on names and times that appear all over a page, so one only opens once the pointer settles.
const OPEN_DELAY_MS = 500
const CLOSE_DELAY_MS = 150

// The card portals out of the DOM, but React still bubbles its events through the trigger's parents,
// which are often clickable (a comment row, a reply summary, a table row), so the card keeps them to itself.
const stopPropagation = (event: SyntheticEvent): void => event.stopPropagation()

type PopoverContentProps = ComponentProps<typeof PopoverContent>

interface QuillHoverCardProps extends Pick<PopoverContentProps, 'side' | 'align' | 'arrow' | 'className'> {
    children: ReactNode
    content: ReactNode
}

/** A card that opens on a settled hover over inline content. It can hold buttons and links, unlike a tooltip. */
export function QuillHoverCard({
    children,
    content,
    side = 'top',
    align,
    arrow,
    className,
}: QuillHoverCardProps): JSX.Element {
    return (
        <Popover>
            <PopoverTrigger
                openOnHover
                delay={OPEN_DELAY_MS}
                closeDelay={CLOSE_DELAY_MS}
                nativeButton={false}
                render={<span />}
            >
                {children}
            </PopoverTrigger>
            <PopoverContent
                side={side}
                align={align}
                arrow={arrow}
                initialFocus={false}
                className={className}
                onClick={stopPropagation}
                onPointerDown={stopPropagation}
                onMouseDown={stopPropagation}
            >
                {content}
            </PopoverContent>
        </Popover>
    )
}
