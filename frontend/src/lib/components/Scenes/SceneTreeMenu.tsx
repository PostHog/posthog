import { IconFolderMove, IconFolderOpen, IconShortcut } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton/LemonButton'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { moveToLogic } from '../FileSystem/MoveTo/moveToLogic'

export function SceneTreeMenu(): JSX.Element | null {
    const { assureVisibility } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { showLayoutPanel, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { addShortcutItem } = useActions(projectTreeDataLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { openMoveToModal } = useActions(moveToLogic)

    return projectTreeRefEntry ? (
        <>
            <LemonButton
                size="small"
                onClick={() => {
                    assureVisibility({ type: 'folder', ref: projectTreeRefEntry.path })
                    showLayoutPanel(true)
                    setActivePanelIdentifier('Project')
                }}
                icon={<IconFolderOpen />}
                data-attr="top-bar-open-in-project-tree-button"
            >
                Open in project tree
            </LemonButton>
            <LemonButton
                size="small"
                onClick={() => openMoveToModal([projectTreeRefEntry])}
                icon={<IconFolderMove />}
                data-attr="top-bar-move-button"
            >
                Move to another folder
            </LemonButton>
            <LemonButton
                size="small"
                onClick={() => addShortcutItem(projectTreeRefEntry)}
                icon={<IconShortcut />}
                data-attr="top-bar-add-to-shortcuts-button"
            >
                Add to shortcuts panel
            </LemonButton>
        </>
    ) : null
}
