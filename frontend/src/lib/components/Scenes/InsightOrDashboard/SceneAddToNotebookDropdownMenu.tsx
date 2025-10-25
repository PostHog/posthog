import { IconPlusSmall } from '@posthog/icons'

import { ButtonPrimitive, ButtonPrimitiveProps } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { NotebookNodeType } from 'scenes/notebooks/types'

import { NodeKind } from '~/queries/schema/schema-general'

import { SceneDataAttrKeyProps } from '../utils'
import { SceneNotebookMenuItems } from './SceneNotebookMenuItems'

type SceneNotebookDropdownMenuProps = SceneDataAttrKeyProps &
    Pick<ButtonPrimitiveProps, 'disabledReasons'> & {
        shortId?: string
    }

export function SceneAddToNotebookDropdownMenu({
    shortId,
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
                        resource: {
                            type: NotebookNodeType.Query,
                            attrs: {
                                query: {
                                    kind: NodeKind.SavedInsightNode,
                                    shortId: shortId,
                                },
                            },
                        },
                    }}
                    dataAttrKey={dataAttrKey}
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
