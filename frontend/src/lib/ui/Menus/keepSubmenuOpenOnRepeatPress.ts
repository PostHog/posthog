import { Menu } from '@base-ui/react/menu'

/**
 * `onOpenChange` for a `Menu.SubmenuRoot` that opens on click.
 *
 * Base UI toggles such a submenu, so pressing its trigger again closes it. Native menus leave it
 * open instead, and so does a hover-opened one, which this keeps the click-opened one in line with.
 * Every other way of closing (Escape, an outside press, picking an item) still goes through.
 */
export function keepSubmenuOpenOnRepeatPress(open: boolean, details: Menu.SubmenuRoot.ChangeEventDetails): void {
    if (!open && details.reason === 'trigger-press') {
        details.cancel()
    }
}
