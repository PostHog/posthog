import './Notebook.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { NotFound } from 'lib/components/NotFound'
import { EditorFocusPosition, JSONContent } from 'lib/components/RichContentEditor/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { NotebookLogicProps, notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { SCRATCHPAD_NOTEBOOK } from '~/models/notebooksModel'

import { AddExperimentsToNotebookModal } from '../AddExperimentsToNotebookModal/AddExperimentsToNotebookModal'
import { AddInsightsToNotebookModal } from '../AddInsightsToNotebookModal/AddInsightsToNotebookModal'
import { Editor } from './Editor'
import { isMarkdownNotebookContent } from './markdownNotebookV2'
import { MarkdownNotebookV2 } from './MarkdownNotebookV2Renderer'
import { NotebookCollabConflictModal } from './NotebookCollabConflictModal'
import { NotebookColumnLeft } from './NotebookColumnLeft'
import { NotebookColumnRight } from './NotebookColumnRight'
import { NotebookConflictWarning } from './NotebookConflictWarning'
import { NotebookHistoryWarning } from './NotebookHistory'
import { NotebookLoadingState } from './NotebookLoadingState'
import { NotebookMergeConflictDetails } from './NotebookMergeConflictDetails'
import { notebookSettingsLogic } from './notebookSettingsLogic'
import { openUpgradeToMarkdownNotebookDialog } from './notebookUpgradeDialog'

export type NotebookProps = NotebookLogicProps & {
    initialAutofocus?: EditorFocusPosition
    initialContent?: JSONContent
    editable?: boolean
    className?: string
    markdownSourceOpen?: boolean
    onMarkdownSourceOpenChange?: (isOpen: boolean) => void
}

export function Notebook({
    shortId,
    mode,
    editable = true,
    initialAutofocus = 'start',
    initialContent,
    cachedNotebook,
    cachedInsightsByShortId,
    cachedInlineQueryResultsByNodeId,
    className,
    markdownSourceOpen,
    onMarkdownSourceOpenChange,
}: NotebookProps): JSX.Element {
    const logicProps: NotebookLogicProps = {
        shortId,
        mode,
        cachedNotebook,
        cachedInsightsByShortId,
        cachedInlineQueryResultsByNodeId,
    }
    const logic = notebookLogic(logicProps)
    const {
        notebook,
        notebookLoading,
        editor,
        conflictWarningVisible,
        isEditable,
        isTemplate,
        notebookMissing,
        content,
        comments,
    } = useValues(logic)
    const { duplicateNotebook, loadNotebook, setEditable, setLocalContent, setContainerSize } = useActions(logic)
    const { isExpanded, isMarkdownExpanded } = useValues(notebookSettingsLogic)
    const { isCommandOpen } = useValues(commandLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    useEffect(() => {
        if (initialContent && mode === 'canvas') {
            setLocalContent(initialContent)
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [notebook])

    useOnMountEffect(() => {
        if (!notebook && !notebookLoading) {
            loadNotebook()
        }
    })

    useEffect(() => {
        setEditable(editable)
    }, [editable]) // oxlint-disable-line exhaustive-deps

    useEffect(() => {
        editor?.setEditable(isEditable)
    }, [isEditable]) // oxlint-disable-line exhaustive-deps

    useEffect(() => {
        if (editor && !isCommandOpen) {
            editor.focus(initialAutofocus)
        }
    }, [editor]) // oxlint-disable-line exhaustive-deps

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        1000: 'medium',
    })

    useEffect(() => {
        setContainerSize(size as 'small' | 'medium')
    }, [size]) // oxlint-disable-line exhaustive-deps

    const isMarkdownNotebook = isMarkdownNotebookContent(content)
    const isContentWidthExpanded = isMarkdownNotebook ? isMarkdownExpanded : isExpanded
    const canUpgradeToMarkdownNotebooks = !!featureFlags[FEATURE_FLAGS.MARKDOWN_NOTEBOOKS]
    const upgradeToMarkdownNotebook = (): void => {
        openUpgradeToMarkdownNotebookDialog({ content, comments, setLocalContent })
    }

    return (
        <BindLogic logic={notebookLogic} props={logicProps}>
            {conflictWarningVisible ? (
                <NotebookConflictWarning />
            ) : !notebook && notebookLoading ? (
                <NotebookLoadingState />
            ) : notebookMissing ? (
                <NotFound object="notebook" />
            ) : (
                <div
                    className={clsx(
                        'Notebook',
                        !isContentWidthExpanded && 'Notebook--compact',
                        isContentWidthExpanded && 'Notebook--expanded',
                        mode && `Notebook--${mode}`,
                        size === 'small' && `Notebook--single-column`,
                        isEditable && 'Notebook--editable',
                        isMarkdownNotebook && 'Notebook--markdown-v2',
                        className
                    )}
                    ref={ref}
                >
                    {isTemplate && (
                        <LemonBanner
                            type="info"
                            action={{
                                onClick: duplicateNotebook,
                                children: 'Create copy',
                            }}
                            className="mb-6"
                        >
                            <b>This is a template.</b> You can create a copy of it to edit and use as your own.
                        </LemonBanner>
                    )}
                    <NotebookHistoryWarning />
                    <NotebookCollabConflictModal />
                    <NotebookMergeConflictDetails />
                    {shortId === SCRATCHPAD_NOTEBOOK.short_id ? (
                        <LemonBanner
                            type="info"
                            action={{
                                children: 'Convert to notebook',
                                onClick: duplicateNotebook,
                            }}
                            className="mb-6"
                        >
                            This is your scratchpad. It is only visible to you and is persisted only in this browser.
                            It's a great place to gather ideas before turning into a saved Notebook!
                        </LemonBanner>
                    ) : null}

                    {isEditable && !isMarkdownNotebook && canUpgradeToMarkdownNotebooks ? (
                        <div className="Notebook__top-actions">
                            <LemonButton type="secondary" onClick={upgradeToMarkdownNotebook}>
                                Convert to Markdown notebooks
                            </LemonButton>
                        </div>
                    ) : null}

                    <div className="Notebook_content">
                        <NotebookColumnLeft />
                        <ErrorBoundary>
                            {isMarkdownNotebook ? (
                                <MarkdownNotebookV2
                                    debugOpen={markdownSourceOpen}
                                    onDebugOpenChange={onMarkdownSourceOpenChange}
                                />
                            ) : (
                                <Editor />
                            )}
                        </ErrorBoundary>
                        <NotebookColumnRight />
                    </div>
                </div>
            )}
            <AddInsightsToNotebookModal />
            <AddExperimentsToNotebookModal />
        </BindLogic>
    )
}
