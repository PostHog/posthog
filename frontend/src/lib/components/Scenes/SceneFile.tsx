import { IconFolderMove, IconFolderOpen, IconShortcut } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { moveToLogic } from '../FileSystem/MoveTo/moveToLogic'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'

export function SceneFile({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    const { assureVisibility } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { showLayoutPanel, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { addShortcutItem } = useActions(projectTreeDataLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { openMoveToModal } = useActions(moveToLogic)

    return projectTreeRefEntry ? (
        <div className="flex flex-col">
            <Label intent="menu">File</Label>
            <DropdownMenu>
                <div className="-ml-1.5">
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive menuItem data-attr={`${dataAttrKey}-file-dropdown-menu-trigger`}>
                            <IconFolderOpen />
                            {splitPath(projectTreeRefEntry.path).slice(0, -1).join('/')}
                            <DropdownMenuOpenIndicator className="ml-auto" />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                </div>
                <DropdownMenuContent align="start" matchTriggerWidth>
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
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    ) : null
}
