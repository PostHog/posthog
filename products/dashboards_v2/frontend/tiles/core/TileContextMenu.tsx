import type { MouseEvent, ReactNode } from 'react'

import { IconEllipsis } from '@posthog/icons'
import {
    Button,
    ContextMenu,
    ContextMenuCheckboxItem,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuLabel,
    ContextMenuRadioGroup,
    ContextMenuRadioItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuTrigger,
} from '@posthog/quill'

import type { MenuAction } from '../../menu/menuAction'
import { MenuActionList, type MenuParts } from '../../menu/MenuActionList'

const CONTEXT_MENU_PARTS: MenuParts = {
    Group: ContextMenuGroup,
    Label: ContextMenuLabel,
    Separator: ContextMenuSeparator,
    Item: ContextMenuItem,
    CheckboxItem: ContextMenuCheckboxItem,
    Sub: ContextMenuSub,
    SubTrigger: ContextMenuSubTrigger,
    SubContent: ContextMenuSubContent,
    RadioGroup: ContextMenuRadioGroup,
    RadioItem: ContextMenuRadioItem,
}

function isUsable(action: MenuAction): boolean {
    if (action.disabledReason) {
        return false
    }
    return action.submenu ? action.submenu.some(isUsable) : true
}

export function hasTileMenu(actions: MenuAction[]): boolean {
    return actions.some(isUsable)
}

/**
 * Opens the tile's actions on right-click. When the person may use none of them, it renders the children alone so the
 * browser's own menu still shows.
 */
export function TileContextMenu({ actions, children }: { actions: MenuAction[]; children: ReactNode }): JSX.Element {
    if (!hasTileMenu(actions)) {
        return <>{children}</>
    }
    return (
        <ContextMenu>
            <ContextMenuTrigger
                render={
                    // A tile inside a section has its own menu, so its right-click must not also open the section's.
                    <div
                        className="TileContextMenu__trigger contents"
                        onContextMenu={(event) => event.stopPropagation()}
                    />
                }
            >
                {children}
            </ContextMenuTrigger>
            {/* Returning focus to the trigger would blur a rename input the menu just opened. */}
            <ContextMenuContent finalFocus={false}>
                <MenuActionList actions={actions} parts={CONTEXT_MENU_PARTS} />
            </ContextMenuContent>
        </ContextMenu>
    )
}

/**
 * Opens the surrounding `TileContextMenu` from a click. It fires a `contextmenu` event at the button, which bubbles to
 * that menu's trigger, so the click and the right-click show the same menu at the same place.
 */
export function TileContextMenuButton({ className }: { className?: string }): JSX.Element {
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
