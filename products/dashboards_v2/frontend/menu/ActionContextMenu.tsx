import {
    type ComponentProps,
    type MouseEvent,
    type ReactNode,
    forwardRef,
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react'

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
    MenuLabel,
} from '@posthog/quill'

import type { MenuAction } from './menuAction'
import { MenuActionList, type MenuParts } from './MenuActionList'

// Quill's dropdown heading inside the context menu's own, so a tile's menu and the dashboard's menu have one heading.
const CapsLabel = forwardRef<HTMLDivElement, ComponentProps<typeof ContextMenuLabel>>(function CapsLabel(
    { children, ...props },
    ref
) {
    return (
        <ContextMenuLabel ref={ref} {...props} className="p-0">
            <MenuLabel>{children}</MenuLabel>
        </ContextMenuLabel>
    )
})

const CONTEXT_MENU_PARTS: MenuParts = {
    Group: ContextMenuGroup,
    Label: CapsLabel,
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

export function hasMenuActions(actions: MenuAction[]): boolean {
    return actions.some(isUsable)
}

function whileLoading(action: MenuAction): MenuAction {
    if (!action.needsLoaded) {
        return action
    }
    return { ...action, disabledReason: action.disabledReason ?? 'Still loading', loading: true }
}

/** Marks a tile that is not mounted yet. Its menu and an image capture tell it apart from a tile that is loading. */
export const TILE_PLACEHOLDER_CLASS = 'DashboardTileGrid__placeholder'

/**
 * The tile does not know what its panel is doing, so it reads the busy mark that every loading state sets. An off-screen
 * tile's placeholder is busy too, but an image capture mounts it, so it does not count.
 */
function isLoading(root: HTMLElement): boolean {
    return Array.from(root.querySelectorAll('[aria-busy="true"]')).some(
        (element) => !element.closest(`.${TILE_PLACEHOLDER_CLASS}`)
    )
}

/**
 * Opens a list of actions, such as a tile's or a tab's, on right-click. When the person may use none of them, it
 * renders the children alone so the browser's own menu still shows.
 */
export function ActionContextMenu({ actions, children }: { actions: MenuAction[]; children: ReactNode }): JSX.Element {
    const trigger = useRef<HTMLDivElement>(null)
    const [open, setOpen] = useState(false)
    const [loading, setLoading] = useState(false)
    const shown = useMemo(() => (loading ? actions.map(whileLoading) : actions), [actions, loading])
    // The tile can finish loading while its menu is open, so the menu watches for that until it closes.
    useEffect(() => {
        const root = trigger.current
        if (!open || !root) {
            return
        }
        const observer = new MutationObserver(() => setLoading(isLoading(root)))
        observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-busy'] })
        return () => observer.disconnect()
    }, [open])
    if (!hasMenuActions(actions)) {
        return <>{children}</>
    }
    return (
        <ContextMenu
            onOpenChange={(next) => {
                setOpen(next)
                if (next && trigger.current) {
                    setLoading(isLoading(trigger.current))
                }
            }}
        >
            <ContextMenuTrigger
                render={
                    // A tile inside a section has its own menu, so its right-click must not also open the section's.
                    <div
                        ref={trigger}
                        className="ActionContextMenu__trigger contents"
                        onContextMenu={(event) => event.stopPropagation()}
                    />
                }
            >
                {children}
            </ContextMenuTrigger>
            {/* Returning focus to the trigger would blur a rename input the menu just opened. */}
            <ContextMenuContent finalFocus={false}>
                <MenuActionList actions={shown} parts={CONTEXT_MENU_PARTS} />
            </ContextMenuContent>
        </ContextMenu>
    )
}

/**
 * Opens the surrounding `ActionContextMenu` from a click. It fires a `contextmenu` event at the button, which bubbles to
 * that menu's trigger, so the click and the right-click show the same menu at the same place.
 */
export function ActionContextMenuButton({ className }: { className?: string }): JSX.Element {
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
