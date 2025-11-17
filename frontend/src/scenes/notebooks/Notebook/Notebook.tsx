import './Notebook.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { EditorFocusPosition, JSONContent } from 'lib/components/RichContentEditor/types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { useWhyDidIRender } from 'lib/hooks/useWhyDidIRender'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { NotebookLogicProps, notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { SCRATCHPAD_NOTEBOOK } from '~/models/notebooksModel'

import { AddInsightsToNotebookModal } from '../AddInsightsToNotebookModal/AddInsightsToNotebookModal'
import { Editor } from './Editor'
import { NotebookColumnLeft } from './NotebookColumnLeft'
import { NotebookColumnRight } from './NotebookColumnRight'
import { NotebookConflictWarning } from './NotebookConflictWarning'
import { NotebookHistoryWarning } from './NotebookHistory'
import { NotebookLoadingState } from './NotebookLoadingState'
import { notebookSettingsLogic } from './notebookSettingsLogic'

export type NotebookProps = NotebookLogicProps & {
    initialAutofocus?: EditorFocusPosition
    initialContent?: JSONContent
    editable?: boolean
}

export function Notebook({
    shortId,
    mode,
    editable = true,
    initialAutofocus = 'start',
    initialContent,
}: NotebookProps): JSX.Element {
    const logicProps: NotebookLogicProps = { shortId, mode }
    const logic = notebookLogic(logicProps)
    const { notebook, notebookLoading, editor, conflictWarningVisible, isEditable, isTemplate, notebookMissing } =
        useValues(logic)
    const { duplicateNotebook, loadNotebook, setEditable, setLocalContent, setContainerSize } = useActions(logic)
    const { isExpanded } = useValues(notebookSettingsLogic)

    useEffect(() => {
        if (initialContent && mode === 'canvas') {
            setLocalContent(initialContent)
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [notebook])

    useWhyDidIRender('Notebook', {
        notebook,
        notebookLoading,
        editor,
        conflictWarningVisible,
        isEditable,
        shortId,
        initialAutofocus,
    })

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
        if (editor) {
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
                        !isExpanded && 'Notebook--compact',
                        mode && `Notebook--${mode}`,
                        size === 'small' && `Notebook--single-column`,
                        isEditable && 'Notebook--editable'
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

                    <div className="Notebook_content">
                        <NotebookColumnLeft />
                        <ErrorBoundary>
                            <Editor />
                        </ErrorBoundary>
                        <NotebookColumnRight />
                    </div>
                </div>
            )}
            <AddInsightsToNotebookModal />
        </BindLogic>
    )
}
