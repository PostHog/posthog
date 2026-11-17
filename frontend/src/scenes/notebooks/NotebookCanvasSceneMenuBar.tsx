import { useActions } from 'kea'

import { IconCopy, IconDownload, IconNotebook, IconTrash, IconUpload } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { loadNotebookFromJSON } from './loadNotebookFromJSON'
import { NotebookLogicProps, notebookLogic } from './Notebook/notebookLogic'

const RESOURCE_TYPE = 'notebook-canvas'

export function NotebookCanvasSceneMenuBar({ logicProps }: { logicProps: NotebookLogicProps }): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <NotebookCanvasSceneMenuBarInner logicProps={logicProps} />
}

function NotebookCanvasSceneMenuBarInner({ logicProps }: { logicProps: NotebookLogicProps }): JSX.Element {
    const { duplicateNotebook, exportJSON, setLocalContent } = useActions(notebookLogic(logicProps))

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-save-as-notebook`,
            label: 'Save as Notebook',
            icon: <IconNotebook />,
            onSelect: () => duplicateNotebook(),
            pinned: { order: 0, variant: 'primary' },
        },
        {
            group: 'file',
            section: 'share',
            id: `${RESOURCE_TYPE}-menubar-share`,
            label: 'Share',
            keywords: ['copy', 'link', 'url'],
            icon: <IconCopy />,
            onSelect: () => void copyToClipboard(window.location.href, 'Canvas URL'),
            pinned: { order: 0, variant: 'secondary' },
        },
        {
            group: 'file',
            section: 'json',
            id: `${RESOURCE_TYPE}-menubar-export-json`,
            label: 'Export as JSON',
            icon: <IconDownload />,
            onSelect: () => exportJSON(),
        },
        {
            group: 'file',
            section: 'json',
            id: `${RESOURCE_TYPE}-menubar-load-json`,
            label: 'Load from JSON',
            icon: <IconUpload />,
            opensFloatingUi: true,
            onSelect: () => loadNotebookFromJSON(setLocalContent),
        },
        {
            group: 'edit',
            section: 'content',
            id: `${RESOURCE_TYPE}-menubar-clear-canvas`,
            label: 'Clear canvas',
            icon: <IconTrash />,
            onSelect: () => setLocalContent({ type: 'doc', content: [] }),
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
