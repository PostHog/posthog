import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { newInternalTab } from 'lib/utils/newInternalTab'

import { CustomMenuProps } from '../types'

interface BrowserLikeMenuProps extends CustomMenuProps {
    href: string
    resetPanelLayout?: (animate: boolean) => void
    onClick?: () => void
}

export function BrowserLikeMenuItems({
    MenuItem = DropdownMenuItem,
    href,
    resetPanelLayout,
    onClick,
}: BrowserLikeMenuProps): JSX.Element {
    return (
        <>
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    newInternalTab(href)
                    resetPanelLayout?.(false)
                    onClick?.()
                }}
                data-attr="tree-item-menu-open-link-button"
            >
                <ButtonPrimitive menuItem>Open link in new tab</ButtonPrimitive>
            </MenuItem>
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    window.open(href, '_blank')
                    onClick?.()
                }}
                data-attr="tree-item-menu-open-link-button"
            >
                <ButtonPrimitive menuItem>Open link in new browser tab</ButtonPrimitive>
            </MenuItem>
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    void navigator.clipboard.writeText(document.location.origin + href)
                    lemonToast.success('Link copied to clipboard')
                }}
                data-attr="tree-item-menu-copy-link-button"
            >
                <ButtonPrimitive menuItem>Copy link address</ButtonPrimitive>
            </MenuItem>
        </>
    )
}
