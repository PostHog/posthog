import { useActions, useValues } from 'kea'

import { IconFolderMove, IconFolderOpen, IconShortcut, IconStar, IconStarFilled } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { moveToLogic } from '../FileSystem/MoveTo/moveToLogic'

export function SceneFile({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    const isAIFirst = useFeatureFlag('AI_FIRST')
    const { assureVisibility } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { showLayoutPanel, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { addShortcutItem, deleteShortcut } = useActions(projectTreeDataLogic)
    const { projectTreeRefEntry, shortcutNonFolderPaths, shortcutData } = useValues(projectTreeDataLogic)
    const { openMoveToModal } = useActions(moveToLogic)

    const itemShortcutPath = projectTreeRefEntry
        ? joinPath([splitPath(projectTreeRefEntry.path).pop() ?? 'Unnamed'])
        : null
    const isAlreadyStarred =
        projectTreeRefEntry &&
        projectTreeRefEntry.type !== 'folder' &&
        itemShortcutPath &&
        shortcutNonFolderPaths.has(itemShortcutPath)

    return projectTreeRefEntry ? (
        <ScenePanelLabel title="Project">
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <ButtonPrimitive variant="panel" menuItem data-attr={`${dataAttrKey}-file-dropdown-menu-trigger`}>
                        <IconFolderOpen />
                        {splitPath(projectTreeRefEntry.path).slice(0, -1).join('/')}
                        <MenuOpenIndicator className="ml-auto" />
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
                                onClick={() => {
                                    if (isAlreadyStarred && itemShortcutPath) {
                                        const shortcut = shortcutData.find(
                                            (s) => s.path === itemShortcutPath && s.type !== 'folder'
                                        )
                                        if (shortcut?.id) {
                                            deleteShortcut(shortcut.id)
                                        }
                                    } else {
                                        addShortcutItem(projectTreeRefEntry)
                                    }
                                }}
                                data-attr={
                                    isAlreadyStarred
                                        ? `${dataAttrKey}-remove-from-shortcuts-dropdown-menu-item`
                                        : `${dataAttrKey}-add-to-shortcuts-dropdown-menu-item`
                                }
                            >
                                {isAIFirst ? (
                                    isAlreadyStarred ? (
                                        <IconStarFilled className="text-warning" />
                                    ) : (
                                        <IconStar />
                                    )
                                ) : (
                                    <IconShortcut />
                                )}
                                {isAIFirst
                                    ? isAlreadyStarred
                                        ? 'Remove from starred'
                                        : 'Add to starred'
                                    : 'Add to shortcuts panel'}
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
        </ScenePanelLabel>
    ) : null
}
