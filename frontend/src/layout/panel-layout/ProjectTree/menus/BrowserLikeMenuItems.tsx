import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'

import { CustomMenuProps } from '../types'

interface BrowserLikeMenuProps extends CustomMenuProps {
    href: string
}

export function BrowserLikeMenuItems({ MenuItem = DropdownMenuItem, href }: BrowserLikeMenuProps): JSX.Element {
    return (
        <>
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    window.open(href, '_blank')
                }}
                data-attr="tree-item-menu-open-link-button"
            >
                <ButtonPrimitive menuItem>Open link in new tab</ButtonPrimitive>
            </MenuItem>
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    void navigator.clipboard.writeText(document.location.origin + href)
                }}
                data-attr="tree-item-menu-copy-link-button"
            >
                <ButtonPrimitive menuItem>Copy link address</ButtonPrimitive>
            </MenuItem>
        </>
    )
}
