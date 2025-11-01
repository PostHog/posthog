import { IconPlusSmall } from '@posthog/icons'

import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { NotebookNodeResource } from 'scenes/notebooks/types'

import { SceneDataAttrKeyProps } from '../utils'
import { SceneNotebookMenuItems } from './SceneNotebookMenuItems'

type SceneNotebookDropdownMenuProps = SceneDataAttrKeyProps &
    Pick<ButtonPrimitiveProps, 'disabledReasons'> & {
        resource: NotebookNodeResource
    }

export function SceneAddToNotebookDropdownMenu({
    resource,
    dataAttrKey,
    disabledReasons,
}: SceneNotebookDropdownMenuProps): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive
                    menuItem
                    data-attr={`${dataAttrKey}-add-to-dropdown-menu`}
                    disabledReasons={disabledReasons}
                >
                    <IconPlusSmall />
                    Add to notebook
                    <DropdownMenuOpenIndicator />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" matchTriggerWidth className="min-w-none max-w-none">
                <SceneNotebookMenuItems
                    notebookSelectButtonProps={{
                        resource: resource,
                    }}
                    dataAttrKey={dataAttrKey}
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
