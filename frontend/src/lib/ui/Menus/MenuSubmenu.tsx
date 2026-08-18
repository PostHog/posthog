import { Menu, type MenuSubmenuTriggerProps } from '@base-ui/react/menu'
import { type ReactNode, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

/**
 * Grace period before an open submenu closes once the pointer leaves the trigger row. Base UI
 * already keeps the submenu open while the pointer travels through the safe polygon between the
 * trigger and the popup; this covers a fast diagonal move that leaves the polygon for a frame.
 */
const CLOSE_DELAY_MS = 100

interface MenuSubmenuProps {
    /** The menu row that opens the submenu, usually a `ButtonPrimitive` with `menuItem`. */
    trigger: MenuSubmenuTriggerProps['render']
    /** Contents of the submenu popup. */
    children: ReactNode
    /** Applied on top of `primitive-menu-content` on the popup. */
    popupClassName?: string
}

/**
 * A menu row that opens a submenu on hover, and also on click.
 *
 * Base UI derives both of its submenu click flags from `openOnHover`. Leaving hover on also sets
 * `ignoreMouse`, so a mouse click on the trigger is ignored and opening depends entirely on a
 * pointer-rest timer; turning hover off is the only way to get the click, and it costs the hover.
 * Neither setting gives us both, so this owns the submenu's open state and opens it on click
 * directly. That is the same contract Radix's `DropdownMenuSubTrigger` has, which is what the other
 * nested menus in the app are built on.
 */
export function MenuSubmenu({ trigger, children, popupClassName }: MenuSubmenuProps): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <Menu.SubmenuRoot open={open} onOpenChange={(nextOpen) => setOpen(nextOpen)}>
            <Menu.SubmenuTrigger closeDelay={CLOSE_DELAY_MS} render={trigger} onClick={() => setOpen(true)} />
            <Menu.Portal>
                <Menu.Positioner className="z-[var(--z-popover)]" collisionPadding={{ top: 50, bottom: 50 }}>
                    <Menu.Popup className={cn('primitive-menu-content', popupClassName)}>{children}</Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.SubmenuRoot>
    )
}
