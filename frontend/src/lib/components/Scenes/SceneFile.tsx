import { useActions, useValues } from 'kea'

import { IconFolderMove, IconFolderOpen, IconShortcut } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'

import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { moveToLogic } from '../FileSystem/MoveTo/moveToLogic'

export function SceneFile({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    const { assureVisibility } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { showLayoutPanel, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { addShortcutItem } = useActions(projectTreeDataLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { openMoveToModal } = useActions(moveToLogic)

    return projectTreeRefEntry ? (
        <ScenePanelLabel title="File">
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive variant="panel" menuItem data-attr={`${dataAttrKey}-file-dropdown-menu-trigger`}>
                        <IconFolderOpen />
                        {splitPath(projectTreeRefEntry.path).slice(0, -1).join('/')}
                        <DropdownMenuOpenIndicator className="ml-auto" />
                    </ButtonPrimitive>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" matchTriggerWidth>
                    <DropdownMenuGroup>
                        <DropdownMenuItem className="w-full">
                            <ButtonPrimitive
                                menuItem
                                onClick={() => {
                                    assureVisibility({ type: 'folder', ref: projectTreeRefEntry.path })
                                    showLayoutPanel(true)
                                    setActivePanelIdentifier('Project')
                                }}
                            >
                                <IconFolderOpen />
                                Open in project tree
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={() => openMoveToModal([projectTreeRefEntry])}
                                data-attr={`${dataAttrKey}-move-to-dropdown-menu-item`}
                            >
                                <IconFolderMove />
                                Move to another folder
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={() => addShortcutItem(projectTreeRefEntry)}
                                data-attr={`${dataAttrKey}-add-to-shortcuts-dropdown-menu-item`}
                            >
                                <IconShortcut />
                                Add to shortcuts panel
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        </ScenePanelLabel>
    ) : null
}
