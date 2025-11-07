import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { newInternalTab } from 'lib/utils/newInternalTab'

import { CustomMenuProps } from '../types'

interface BrowserLikeMenuProps extends CustomMenuProps {
    href: string
    resetPanelLayout?: (animate: boolean) => void
}

export const BrowserLikeMenuItems = ({
    MenuItem = DropdownMenuItem,
    href,
    resetPanelLayout,
}: BrowserLikeMenuProps): JSX.Element => {
    const handleOpenLinkInNewPostHogTab = (e: React.MouseEvent<HTMLElement>): void => {
        e.stopPropagation()
        newInternalTab(href)
        resetPanelLayout?.(false)
    }

    return (
        <>
            <MenuItem asChild onClick={handleOpenLinkInNewPostHogTab} data-attr="tree-item-menu-open-link-button">
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
export const BrowserLikeMenuItemsLoading = (): JSX.Element => {
    return (
        <>
            <WrappingLoadingSkeleton fullWidth>
                <ButtonPrimitive menuItem inert>
                    Open link in new PostHog tab
                </ButtonPrimitive>
            </WrappingLoadingSkeleton>
            <WrappingLoadingSkeleton fullWidth>
                <ButtonPrimitive menuItem inert>
                    Open link in new browser tab
                </ButtonPrimitive>
            </WrappingLoadingSkeleton>
            <WrappingLoadingSkeleton fullWidth>
                <ButtonPrimitive menuItem inert>
                    Copy link address
                </ButtonPrimitive>
            </WrappingLoadingSkeleton>
        </>
    )
}

BrowserLikeMenuItems.displayName = 'BrowserLikeMenuItems'
