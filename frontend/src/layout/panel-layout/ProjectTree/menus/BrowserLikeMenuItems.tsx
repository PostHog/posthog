import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { isTrustedPostHogUrl } from 'lib/utils/trustedUrl'

import { CustomMenuProps } from '../types'

interface BrowserLikeMenuProps extends CustomMenuProps {
    href: string
    resetPanelLayout?: (animate: boolean) => void
    onClick?: () => void
}

export function BrowserLikeMenuItems({
    MenuItem = DropdownMenuItem,
    href,
    onClick,
}: BrowserLikeMenuProps): JSX.Element {
    return (
        <>
            <MenuItem
                asChild
                onClick={(e) => {
                    e.stopPropagation()
                    // `href` is server-supplied for tree and shortcut rows, and window.open honors
                    // whatever scheme it is handed, unlike Link which rewrites its target.
                    if (!isTrustedPostHogUrl(href)) {
                        return
                    }
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
