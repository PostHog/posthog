import { useActions } from 'kea'

import { DropdownMenuGroup, DropdownMenuItem } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'

interface FlatNavProductLinkMenuItemsProps {
    productPath: string
    href: string
}

/** The items every product row offers in the tree sidebar menu, for products that also have their own menu. */
export function FlatNavProductLinkMenuItems({ productPath, href }: FlatNavProductLinkMenuItemsProps): JSX.Element {
    const { setProductEnabled } = useActions(customProductsLogic)
    const absoluteUrl = urls.absolute(urls.currentProject(href))

    return (
        <DropdownMenuGroup>
            <DropdownMenuItem
                onClick={() => window.open(absoluteUrl, '_blank')}
                data-attr="flat-nav-menu-open-in-new-tab"
            >
                Open link in new browser tab
            </DropdownMenuItem>
            <DropdownMenuItem
                onClick={() => void copyToClipboard(absoluteUrl, 'link')}
                data-attr="flat-nav-menu-copy-link"
            >
                Copy link address
            </DropdownMenuItem>
            <DropdownMenuItem
                onClick={() => setProductEnabled(productPath, false)}
                data-attr="flat-nav-menu-remove-from-sidebar"
            >
                Remove from sidebar
            </DropdownMenuItem>
        </DropdownMenuGroup>
    )
}
