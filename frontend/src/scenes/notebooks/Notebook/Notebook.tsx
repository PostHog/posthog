import './Notebook.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { useWhyDidIRender } from 'lib/hooks/useWhyDidIRender'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { useEffect } from 'react'
import { notebookLogic, NotebookLogicProps } from 'scenes/notebooks/Notebook/notebookLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { SCRATCHPAD_NOTEBOOK } from '~/models/notebooksModel'

import { Editor } from './Editor'
import { NotebookColumnLeft } from './NotebookColumnLeft'
import { NotebookColumnRight } from './NotebookColumnRight'
import { NotebookConflictWarning } from './NotebookConflictWarning'
import { NotebookHistoryWarning } from './NotebookHistory'
import { NotebookLoadingState } from './NotebookLoadingState'
import { notebookSettingsLogic } from './notebookSettingsLogic'
import { EditorFocusPosition, JSONContent } from 'lib/components/RichContentEditor/types'

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
    }, [notebook, initialContent, setLocalContent, mode])

    useWhyDidIRender('Notebook', {
        notebook,
        notebookLoading,
        editor,
        conflictWarningVisible,
        isEditable,
        shortId,
        initialAutofocus,
    })

    useEffect(() => {
        if (!notebook && !notebookLoading) {
            loadNotebook()
        }
    }, [notebook, loadNotebook, notebookLoading])

    useEffect(() => {
        setEditable(editable)
    }, [editable, setEditable])

    useEffect(() => {
        editor?.setEditable(isEditable)
    }, [isEditable, editor])

    useEffect(() => {
        if (editor) {
            editor.focus(initialAutofocus)
        }
    }, [editor, initialAutofocus])

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        1000: 'medium',
    })

    useEffect(() => {
        setContainerSize(size as 'small' | 'medium')
    }, [size, setContainerSize])

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
                            className="my-4"
                            action={{
                                onClick: duplicateNotebook,
                                children: 'Create copy',
                            }}
                        >
                            <b>This is a template.</b> You can create a copy of it to edit and use as your own.
                        </LemonBanner>
                    )}

                    <NotebookHistoryWarning />
                    {shortId === SCRATCHPAD_NOTEBOOK.short_id ? (
                        <LemonBanner
                            type="info"
                            className="my-4"
                            action={{
                                children: 'Convert to Notebook',
                                onClick: duplicateNotebook,
                            }}
                        >
                            This is your scratchpad. It is only visible to you and is persisted only in this browser.
                            It's a great place to gather ideas before turning into a saved Notebook!
                        </LemonBanner>
                    ) : null}

                    <div className="flex flex-1 justify-center">
                        <NotebookColumnLeft />
                        <ErrorBoundary>
                            <Editor />
                        </ErrorBoundary>
                        <NotebookColumnRight />
                    </div>
                </div>
            )}
        </BindLogic>
    )
}
