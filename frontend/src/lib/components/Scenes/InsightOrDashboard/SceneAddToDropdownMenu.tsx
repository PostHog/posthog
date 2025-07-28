import { IconPlus } from '@posthog/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { SceneNotebookMenuItems } from './SceneNotebookMenuItems'
import { NodeKind } from '~/queries/schema/schema-general'
import { SceneDataAttrKeyProps } from '../utils'
import { NotebookNodeType } from 'scenes/notebooks/types'

type SceneAddToDropdownMenuProps = {
    onClick?: () => void
}

type SceneNotebookDropdownMenuProps = SceneDataAttrKeyProps & {
    notebook?: boolean
    dashboard?: SceneAddToDropdownMenuProps
    shortId?: string
}

export function SceneAddToDropdownMenu({
    notebook,
    dashboard,
    shortId,
    dataAttrKey,
}: SceneNotebookDropdownMenuProps): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive menuItem data-attr={`${dataAttrKey}-add-to-dropdown-menu`}>
                    <IconPlus />
                    Add to...
                    <DropdownMenuOpenIndicator />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" matchTriggerWidth>
                <DropdownMenuSub>
                    {notebook && (
                        <>
                            <DropdownMenuSubTrigger asChild>
                                <ButtonPrimitive menuItem data-attr={`${dataAttrKey}-add-to-notebook-dropdown-menu`}>
                                    Notebook
                                    <DropdownMenuOpenIndicator intent="sub" />
                                </ButtonPrimitive>
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
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
                            </DropdownMenuSubContent>
                        </>
                    )}
                </DropdownMenuSub>
                {dashboard && (
                    <DropdownMenuItem>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => {
                                dashboard.onClick?.()
                            }}
                            data-attr={`${dataAttrKey}-add-to-dashboard-dropdown-menu`}
                        >
                            Dashboard
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
