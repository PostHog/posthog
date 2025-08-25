import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { sceneLogic } from 'scenes/sceneLogic'

import { CustomMenuProps } from '../types'

interface BrowserLikeMenuProps extends CustomMenuProps {
    href: string
    canOpenInPostHogTab: boolean
    resetPanelLayout: (animate: boolean) => void
}

export function BrowserLikeMenuItems({
    MenuItem = DropdownMenuItem,
    href,
    canOpenInPostHogTab,
    resetPanelLayout,
}: BrowserLikeMenuProps): JSX.Element {
    return (
        <>
            {canOpenInPostHogTab ? (
                <MenuItem
                    asChild
                    onClick={(e) => {
                        e.stopPropagation()
                        sceneLogic.findMounted()?.actions.newTab(href)
                        resetPanelLayout(false)
                    }}
                    data-attr="tree-item-menu-open-link-button"
                >
                    <ButtonPrimitive menuItem>Open link in new PostHog tab</ButtonPrimitive>
                </MenuItem>
            ) : null}
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    window.open(href, '_blank')
                }}
                data-attr="tree-item-menu-open-link-button"
            >
                <ButtonPrimitive menuItem>Open link in new {canOpenInPostHogTab ? 'browser ' : ''}tab</ButtonPrimitive>
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
