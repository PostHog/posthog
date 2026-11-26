import type { MouseEvent } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { Button } from '@posthog/quill'

/**
 * Opens the tile's right-click menu from a click. It fires a `contextmenu` event at the button, which bubbles to the
 * menu trigger around the card, so the click and the right-click show the same menu at the same place.
 */
export function TileMenuButton({ className }: { className?: string }): JSX.Element {
    const openMenu = (event: MouseEvent<HTMLButtonElement>): void => {
        const rect = event.currentTarget.getBoundingClientRect()
        event.currentTarget.dispatchEvent(
            new globalThis.MouseEvent('contextmenu', {
                bubbles: true,
                cancelable: true,
                clientX: rect.right,
                clientY: rect.bottom,
            })
        )
    }
    return (
        <Button
            size="icon-xs"
            className={className}
            tooltip="More"
            aria-label="More"
            aria-haspopup="menu"
            data-attr="dashboard-v2-tile-menu"
            onClick={openMenu}
        >
            {/* Quill draws an extra small button's icon at 10px, too small to read as a menu on a tile. */}
            <IconEllipsis className="size-3.5" />
        </Button>
    )
}
