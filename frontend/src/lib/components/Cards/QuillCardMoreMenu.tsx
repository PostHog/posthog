import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'

export function QuillCardMoreMenu({ items, tooltip = 'More' }: { items: JSX.Element; tooltip?: string }): JSX.Element {
    return (
        <DropdownMenu
            onOpenChange={(open, details) => {
                if (closesIntoLemonPopover(open, details)) {
                    details.cancel()
                }
            }}
        >
            <DropdownMenuTrigger
                render={<Button size="icon" aria-label={tooltip} tooltip={tooltip} data-attr="more-button" />}
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">{items}</DropdownMenuContent>
        </DropdownMenu>
    )
}
