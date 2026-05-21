import { useActions, useValues } from 'kea'

import { IconFolderMove, IconFolderOpen, IconStar, IconStarFilled } from '@posthog/icons'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { SceneMenuBarItem } from '~/layout/scenes/components/SceneMenuBar'

import { moveToLogic } from '../FileSystem/MoveTo/moveToLogic'

type SceneMenuBarFileItemsProps = {
    /** Used as a prefix on data-attr for testing */
    dataAttrKey: string
}

/**
 * File-system actions for the current scene's tree entry, intended to be placed inside
 * a <SceneMenuBarMenu label="File">. Returns null if no project tree entry is registered.
 */
export function SceneMenuBarFileItems({ dataAttrKey }: SceneMenuBarFileItemsProps): JSX.Element | null {
    const { assureVisibility } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { showLayoutPanel, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { addShortcutItem, deleteShortcut } = useActions(projectTreeDataLogic)
    const { projectTreeRefEntry, shortcutNonFolderPaths, shortcutData } = useValues(projectTreeDataLogic)
    const { openMoveToModal } = useActions(moveToLogic)

    if (!projectTreeRefEntry) {
        return null
    }

    const itemShortcutPath = joinPath([splitPath(projectTreeRefEntry.path).pop() ?? 'Unnamed'])
    const isAlreadyStarred = projectTreeRefEntry.type !== 'folder' && shortcutNonFolderPaths.has(itemShortcutPath)

    return (
        <>
            <SceneMenuBarItem
                opensFloatingUi
                onClick={() => {
                    assureVisibility({ type: 'folder', ref: projectTreeRefEntry.path })
                    showLayoutPanel(true)
                    setActivePanelIdentifier('Project')
                }}
                data-attr={`${dataAttrKey}-menubar-open-in-project-tree`}
            >
                <IconFolderOpen />
                Open in project tree
            </SceneMenuBarItem>
            <SceneMenuBarItem
                opensFloatingUi
                onClick={() => openMoveToModal([projectTreeRefEntry])}
                data-attr={`${dataAttrKey}-menubar-move-to`}
            >
                <IconFolderMove />
                Move to another folder
            </SceneMenuBarItem>
            <SceneMenuBarItem
                onClick={() => {
                    if (isAlreadyStarred) {
                        const shortcut = shortcutData.find((s) => s.path === itemShortcutPath && s.type !== 'folder')
                        if (shortcut?.id) {
                            deleteShortcut(shortcut.id)
                        }
                    } else {
                        addShortcutItem(projectTreeRefEntry)
                    }
                }}
                data-attr={
                    isAlreadyStarred
                        ? `${dataAttrKey}-menubar-remove-from-starred`
                        : `${dataAttrKey}-menubar-add-to-starred`
                }
            >
                {isAlreadyStarred ? <IconStarFilled className="text-warning" /> : <IconStar />}
                {isAlreadyStarred ? 'Remove from starred' : 'Add to starred'}
            </SceneMenuBarItem>
        </>
    )
}
