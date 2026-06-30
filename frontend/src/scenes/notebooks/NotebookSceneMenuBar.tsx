import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconDownload, IconOpenSidebar, IconShare, IconTrash } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import {
    SceneMenuBar,
    SceneMenuBarCheckboxItem,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
    SceneMenuBarSubMenu,
} from '~/layout/scenes/components/SceneMenuBar'
import { notebooksModel } from '~/models/notebooksModel'

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
    const logic = notebookLogic({ shortId })
    const { notebook, showHistory, isLocalOnly, content } = useValues(logic)
    const { openShareModal, duplicateNotebook, exportJSON, downloadMarkdown, copyMarkdown, setShowHistory } =
        useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { showTableOfContents, isExpanded, isMarkdownExpanded, showKernelInfo } = useValues(notebookSettingsLogic)
    const { setShowTableOfContents, setIsExpanded, setIsMarkdownExpanded, setShowKernelInfo } =
        useActions(notebookSettingsLogic)
    const { selectNotebook } = useActions(notebookPanelLogic)
    const isMarkdownNotebook = isMarkdownNotebookContent(content)
    const canDelete = !isLocalOnly && !notebook?.is_template
    const showKernelToggle = !!featureFlags[FEATURE_FLAGS.NOTEBOOK_PYTHON]
    const isContentWidthExpanded = isMarkdownNotebook ? isMarkdownExpanded : isExpanded
    const setContentWidthExpanded = isMarkdownNotebook ? setIsMarkdownExpanded : setIsExpanded

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                <SceneMenuBarSubMenu label="Export">
                    {isMarkdownNotebook ? (
                        <>
                            <SceneMenuBarItem
                                onClick={() => downloadMarkdown()}
                                data-attr={`${RESOURCE_TYPE}-menubar-download-markdown`}
                            >
                                <IconDownload />
                                Download markdown
                            </SceneMenuBarItem>
                            <SceneMenuBarItem
                                onClick={() => copyMarkdown()}
                                data-attr={`${RESOURCE_TYPE}-menubar-copy-markdown`}
                            >
                                <IconCopy />
                                Copy markdown
                            </SceneMenuBarItem>
                        </>
                    ) : (
                        <SceneMenuBarItem
                            onClick={() => exportJSON()}
                            data-attr={`${RESOURCE_TYPE}-menubar-export-json`}
                        >
                            <IconDownload />
                            Export JSON
                        </SceneMenuBarItem>
                    )}
                </SceneMenuBarSubMenu>
                <SceneMenuBarItem
                    opensFloatingUi
                    onClick={() => openShareModal()}
                    data-attr={`${RESOURCE_TYPE}-menubar-share`}
                >
                    <IconShare />
                    Share
                </SceneMenuBarItem>
                {canDelete && (
                    <>
                        <SceneMenuBarSeparator />
                        <SceneMenuBarItem
                            variant="destructive"
                            onClick={() => {
                                notebooksModel.actions.deleteNotebook(shortId, notebook?.title)
                                router.actions.push(urls.notebooks())
                            }}
                            data-attr={`${RESOURCE_TYPE}-menubar-delete`}
                        >
                            <IconTrash />
                            Delete
                        </SceneMenuBarItem>
                    </>
                )}
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="Edit" dataAttr={`${RESOURCE_TYPE}-menubar-edit`}>
                <SceneMenuBarItem onClick={() => duplicateNotebook()} data-attr={`${RESOURCE_TYPE}-menubar-duplicate`}>
                    <IconCopy />
                    Duplicate
                </SceneMenuBarItem>
                <SceneMenuBarSeparator />
                <SceneMenuBarCheckboxItem
                    checked={showHistory}
                    onCheckedChange={(checked) => setShowHistory(checked)}
                    data-attr={`${RESOURCE_TYPE}-menubar-show-history`}
                >
                    Show history
                </SceneMenuBarCheckboxItem>
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="View" dataAttr={`${RESOURCE_TYPE}-menubar-view`}>
                {/* Table of contents only applies to rich (non-markdown) notebooks. */}
                {!isMarkdownNotebook && (
                    <SceneMenuBarCheckboxItem
                        checked={showTableOfContents}
                        onCheckedChange={(checked) => setShowTableOfContents(checked)}
                        data-attr={`${RESOURCE_TYPE}-menubar-toc`}
                    >
                        Table of contents
                    </SceneMenuBarCheckboxItem>
                )}
                <SceneMenuBarCheckboxItem
                    checked={isContentWidthExpanded}
                    onCheckedChange={(checked) => setContentWidthExpanded(checked)}
                    data-attr={`${RESOURCE_TYPE}-menubar-fill-width`}
                >
                    Fill content width
                </SceneMenuBarCheckboxItem>
                {showKernelToggle && (
                    <SceneMenuBarCheckboxItem
                        checked={showKernelInfo}
                        onCheckedChange={(checked) => setShowKernelInfo(checked)}
                        data-attr={`${RESOURCE_TYPE}-menubar-kernel-info`}
                    >
                        Kernel info
                    </SceneMenuBarCheckboxItem>
                )}
                <SceneMenuBarSeparator />
                <SceneMenuBarItem
                    opensFloatingUi
                    onClick={() => selectNotebook(shortId)}
                    data-attr={`${RESOURCE_TYPE}-menubar-open-in-panel`}
                >
                    <IconOpenSidebar />
                    Open in context panel
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
