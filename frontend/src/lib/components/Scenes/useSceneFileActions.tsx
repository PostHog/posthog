import { useActions, useValues } from 'kea'

import { IconFolderMove, IconFolderOpen, IconStar, IconStarFilled } from '@posthog/icons'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { PROJECT_TREE_KEY, projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import type { SceneAction, SceneActionGroup } from '~/layout/scenes/sceneActions/sceneActionModel'

import { moveToLogic } from '../FileSystem/MoveTo/moveToLogic'
import { sceneFileLogic } from './sceneFileLogic'

interface SceneFileActionsOptions {
    group?: SceneActionGroup
    section?: string
}

/**
 * File-system actions for the current scene's tree entry: open in the project tree, move, star. Empty when
 * `sceneFileLogic.hasFileItems` is false.
 */
export function useSceneFileActions(
    dataAttrKey: string,
    { group = 'file', section = 'project-tree' }: SceneFileActionsOptions = {}
): SceneAction[] {
    const { fileItemsEntry: entry } = useValues(sceneFileLogic)
    const { assureVisibility } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { showLayoutPanel, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { addShortcutItem, deleteShortcut } = useActions(projectTreeDataLogic)
    const { shortcutNonFolderPaths, shortcutData } = useValues(projectTreeDataLogic)
    const { openMoveToModal } = useActions(moveToLogic)
    if (!entry) {
        return []
    }

    const shortcutPath = joinPath([splitPath(entry.path).pop() ?? 'Unnamed'])
    const starred = entry.type !== 'folder' && shortcutNonFolderPaths.has(shortcutPath)

    return [
        {
            group,
            section,
            id: `${dataAttrKey}-menubar-open-in-project-tree`,
            label: 'Open in project tree',
            icon: <IconFolderOpen />,
            opensFloatingUi: true,
            onSelect: () => {
                assureVisibility({ type: 'folder', ref: entry.path })
                showLayoutPanel(true)
                setActivePanelIdentifier('Project')
            },
        },
        {
            group,
            section,
            id: `${dataAttrKey}-menubar-move-to`,
            label: 'Move to another folder',
            icon: <IconFolderMove />,
            opensFloatingUi: true,
            onSelect: () => openMoveToModal([entry]),
        },
        {
            group,
            section,
            id: starred ? `${dataAttrKey}-menubar-remove-from-starred` : `${dataAttrKey}-menubar-add-to-starred`,
            label: starred ? 'Remove from starred' : 'Add to starred',
            keywords: ['star', 'favorite'],
            icon: starred ? <IconStarFilled className="text-warning" /> : <IconStar />,
            onSelect: () => {
                if (!starred) {
                    addShortcutItem(entry)
                    return
                }
                const shortcut = shortcutData.find((s) => s.path === shortcutPath && s.type !== 'folder')
                if (shortcut?.id) {
                    deleteShortcut(shortcut.id)
                }
            },
        },
    ]
}
