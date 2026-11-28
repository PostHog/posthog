import { useActions, useMountedLogic, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { PeekDrawer } from 'lib/components/PeekDrawer/PeekDrawer'
import { LinkPrimitive } from 'lib/lemon-ui/Link/Link'
import { sceneConfigurations } from 'scenes/scenes'
import { urlToResource } from 'scenes/urls'

import { SidebarPinButton } from '~/layout/today/sidebar/SidebarPinButton'

import { ItemPeekBody } from './ItemPeekBody'
import { itemPeekLogic } from './itemPeekLogic'
import { useItemPeekName } from './useItemPeekName'

export function ItemPeekDrawer(): JSX.Element | null {
    useMountedLogic(itemPeekLogic)
    const { target, isOpen } = useValues(itemPeekLogic)
    const { closeItemPeek, viewItemPeek } = useActions(itemPeekLogic)
    const name = useItemPeekName()

    if (!target) {
        return null
    }

    const resource = urlToResource(target.path)
    const pinType = resource?.type ?? sceneConfigurations[target.sceneId]?.iconType ?? 'default_icon_type'

    return (
        <PeekDrawer
            open={isOpen}
            onClose={closeItemPeek}
            title={name}
            data-attr="item-peek-drawer"
            actions={
                <>
                    <SidebarPinButton
                        target={{ type: pinType, ref: resource?.ref, name, href: target.href }}
                        size="icon-sm"
                        dataAttr="item-peek-pin"
                    />
                    <Button
                        size="sm"
                        variant="outline"
                        // The drawer skips its own link, so this one navigates to the full page.
                        render={<LinkPrimitive to={target.href} onClick={viewItemPeek} />}
                        data-attr="item-peek-view"
                    >
                        View
                        <IconArrowRight />
                    </Button>
                </>
            }
        >
            <ItemPeekBody />
        </PeekDrawer>
    )
}
