import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconDownload, IconOpenSidebar, IconShare, IconTrash } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { useScenePinAction } from 'scenes/analytics/useScenePinAction'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { notebooksModel } from '~/models/notebooksModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { notebookExportLogic } from 'products/notebooks/frontend/notebookExportLogic'

import { isMarkdownNotebookContent } from './Notebook/markdownNotebookV2'
import { notebookLogic } from './Notebook/notebookLogic'
import { notebookSettingsLogic } from './Notebook/notebookSettingsLogic'
import { notebookPanelLogic } from './NotebookPanel/notebookPanelLogic'

const RESOURCE_TYPE = 'notebook'

export function NotebookSceneMenuBar({ shortId }: { shortId: string }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <NotebookSceneMenuBarInner shortId={shortId} />
}

function NotebookSceneMenuBarInner({ shortId }: { shortId: string }): JSX.Element {
    const { preparePrint } = useActions(notebookExportLogic({ shortId }))
    const logic = notebookLogic({ shortId })
    const { notebook, showHistory, isLocalOnly, content, showVariables } = useValues(logic)
    const { openShareModal, duplicateNotebook, downloadMarkdown, copyMarkdown, setShowHistory } = useActions(logic)
    const { isMarkdownExpanded, showKernelInfo, isJupyterMode } = useValues(notebookSettingsLogic)
    const { setIsMarkdownExpanded, setShowKernelInfo, setShowVariables, setIsJupyterMode } =
        useActions(notebookSettingsLogic)
    const { selectNotebook } = useActions(notebookPanelLogic)
    const pinActions = useScenePinAction(RESOURCE_TYPE)
    const canDelete = !isLocalOnly && !notebook?.is_template
    // The kernel info panel only renders for markdown (V2) notebooks, so hide the toggle elsewhere
    const isMarkdownNotebook = isMarkdownNotebookContent(content)
    const sharingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SharingConfiguration,
        AccessControlLevel.Viewer
    )

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'export',
            type: 'submenu',
            id: `${RESOURCE_TYPE}-menubar-export`,
            label: 'Export',
            items: [
                {
                    id: 'notebook-menubar-print-pdf',
                    label: 'Print / save PDF',
                    icon: <IconDownload />,
                    onSelect: preparePrint,
                },
                {
                    id: `${RESOURCE_TYPE}-menubar-download-markdown`,
                    label: 'Download .md',
                    icon: <IconDownload />,
                    onSelect: () => downloadMarkdown(),
                },
                {
                    id: `${RESOURCE_TYPE}-menubar-copy-markdown`,
                    label: 'Copy markdown',
                    icon: <IconCopy />,
                    onSelect: () => copyMarkdown(),
                },
            ],
        },
        {
            group: 'file',
            section: 'export',
            id: `${RESOURCE_TYPE}-menubar-share`,
            label: 'Share',
            icon: <IconShare />,
            opensFloatingUi: true,
            disabledReason: sharingDisabledReason ?? undefined,
            onSelect: () => openShareModal(),
        },
        ...(canDelete
            ? ([
                  {
                      group: 'file',
                      section: 'delete',
                      id: `${RESOURCE_TYPE}-menubar-delete`,
                      label: 'Delete',
                      icon: <IconTrash />,
                      destructive: true,
                      onSelect: () => {
                          notebooksModel.actions.deleteNotebook(shortId, notebook?.title)
                          router.actions.push(urls.notebooks())
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'edit',
            section: 'actions',
            id: `${RESOURCE_TYPE}-menubar-duplicate`,
            label: 'Duplicate',
            icon: <IconCopy />,
            onSelect: () => duplicateNotebook(),
        },
        ...pinActions.map((action) => ({ ...action, section: 'actions' })),
        {
            group: 'edit',
            section: 'toggles',
            type: 'checkbox',
            id: `${RESOURCE_TYPE}-menubar-show-history`,
            label: 'Show history',
            checked: showHistory,
            onCheckedChange: (checked) => setShowHistory(checked),
        },
        {
            group: 'view',
            section: 'toggles',
            type: 'checkbox',
            id: `${RESOURCE_TYPE}-menubar-fill-width`,
            label: 'Fill content width',
            checked: isMarkdownExpanded,
            onCheckedChange: (checked) => setIsMarkdownExpanded(checked),
        },
        ...(isMarkdownNotebook
            ? ([
                  {
                      group: 'view',
                      section: 'toggles',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-kernel-info`,
                      label: 'Kernel info',
                      checked: showKernelInfo,
                      onCheckedChange: (checked) => setShowKernelInfo(checked),
                  },
                  {
                      group: 'view',
                      section: 'toggles',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-variables`,
                      label: 'Variables',
                      checked: showVariables,
                      onCheckedChange: (checked) => setShowVariables(checked),
                  },
                  {
                      group: 'view',
                      section: 'toggles',
                      type: 'checkbox',
                      id: `${RESOURCE_TYPE}-menubar-jupyter-mode`,
                      label: 'Jupyter mode',
                      checked: isJupyterMode,
                      onCheckedChange: (checked) => setIsJupyterMode(checked),
                  },
              ] satisfies SceneAction[])
            : []),
        {
            group: 'view',
            section: 'panel',
            id: `${RESOURCE_TYPE}-menubar-open-in-panel`,
            label: 'Open in context panel',
            icon: <IconOpenSidebar />,
            opensFloatingUi: true,
            onSelect: () => selectNotebook(shortId),
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
