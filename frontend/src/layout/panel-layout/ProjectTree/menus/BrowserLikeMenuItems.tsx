import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { sceneLogic } from 'scenes/sceneLogic'

import { CustomMenuProps } from '../types'

interface BrowserLikeMenuProps extends CustomMenuProps {
    href: string
    resetPanelLayout?: (animate: boolean) => void
}

export function BrowserLikeMenuItems({
    MenuItem = DropdownMenuItem,
    href,
    resetPanelLayout,
}: BrowserLikeMenuProps): JSX.Element {
    return (
        <>
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    sceneLogic.findMounted()?.actions.newTab(href)
                    resetPanelLayout?.(false)
                }}
                data-attr="tree-item-menu-open-link-button"
            >
                <ButtonPrimitive menuItem>Open link in new PostHog tab</ButtonPrimitive>
            </MenuItem>
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    window.open(href, '_blank')
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
