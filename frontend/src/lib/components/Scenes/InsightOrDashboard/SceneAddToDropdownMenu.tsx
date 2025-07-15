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
import { NotebookNodeType } from '~/types'
import { NodeKind } from '~/queries/schema/schema-general'

type SceneAddToDropdownMenuProps = {
    onClick?: () => void
}

type SceneNotebookDropdownMenuProps = {
    notebook?: boolean
    dashboard?: SceneAddToDropdownMenuProps
    shortId?: string
}

export function SceneAddToDropdownMenu({ notebook, dashboard, shortId }: SceneNotebookDropdownMenuProps): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive menuItem>
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
                                <ButtonPrimitive menuItem>
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
                        >
                            Dashboard
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
