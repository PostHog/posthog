import { useActions } from 'kea'

import { IconComment } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SidePanelTab } from '~/types'

import { SceneDataAttrKeyProps } from './utils'

export function SceneComment({ dataAttrKey }: SceneDataAttrKeyProps): JSX.Element {
    const { openSidePanel } = useActions(sidePanelLogic)

    return (
        <ButtonPrimitive
            menuItem
            onClick={() => openSidePanel(SidePanelTab.Discussion)}
            data-attr={`${dataAttrKey}-comment-button`}
            tooltip="Discuss resource"
        >
            <IconComment />
            Comment
        </ButtonPrimitive>
    )
}
