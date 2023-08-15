import { useEffect, useMemo } from 'react'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { BindLogic, useActions, useValues } from 'kea'
import './Notebook.scss'

import { sampleOne } from 'lib/utils'
import { NotFound } from 'lib/components/NotFound'
import clsx from 'clsx'
import { notebookSettingsLogic } from './notebookSettingsLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SCRATCHPAD_NOTEBOOK } from './notebooksListLogic'
import { NotebookConflictWarning } from './NotebookConflictWarning'
import { NotebookLoadingState } from './NotebookLoadingState'
import { Editor } from './Editor'
import { EditorFocusPosition } from './utils'

export type NotebookProps = {
    shortId: string
    editable?: boolean
    initialAutofocus?: EditorFocusPosition
}

const PLACEHOLDER_TITLES = ['Release notes', 'Product roadmap', 'Meeting notes', 'Bug analysis']

export function Notebook({ shortId, editable = false, initialAutofocus = null }: NotebookProps): JSX.Element {
    const logic = notebookLogic({ shortId })
    const { notebook, content, notebookLoading, isEmpty, editor, conflictWarningVisible } = useValues(logic)
    const { setEditor, onEditorUpdate, duplicateNotebook, loadNotebook, setEditable, onEditorSelectionUpdate } =
        useActions(logic)
    const { isExpanded } = useValues(notebookSettingsLogic)

    const headingPlaceholder = useMemo(() => sampleOne(PLACEHOLDER_TITLES), [shortId])

    useEffect(() => {
        if (!notebook && !notebookLoading) {
            loadNotebook()
        }
    }, [])

    useEffect(() => {
        setEditable(editable)
    }, [editable])

    useEffect(() => {
        if (editor) {
            editor.focus(initialAutofocus)
        }
    }, [editor])

    // TODO - Render a special state if the notebook is empty

    if (conflictWarningVisible) {
        return <NotebookConflictWarning />
    } else if (!notebook && notebookLoading) {
        return <NotebookLoadingState />
    } else if (!notebook) {
        return <NotFound object="notebook" />
    } else if (isEmpty && !editable) {
        return (
            <div className="NotebookEditor">
                <h1>
                    <i>Untitled</i>
                </h1>
            </div>
        )
    }

    return (
        <BindLogic logic={notebookLogic} props={{ shortId }}>
            <div className={clsx('Notebook', !isExpanded && 'Notebook--compact', editable && 'Notebook--editable')}>
                {notebook.is_template && (
                    <LemonBanner
                        type="info"
                        className="my-4"
                        action={{
                            onClick: duplicateNotebook,
                            children: 'Create notebook',
                        }}
                    >
                        <b>This is a template.</b> You can create a copy of it to edit and use as your own.
                    </LemonBanner>
                )}

                {notebook.short_id === SCRATCHPAD_NOTEBOOK.short_id ? (
                    <LemonBanner
                        type="info"
                        action={{
                            children: 'Convert to Notebook',
                            onClick: duplicateNotebook,
                        }}
                    >
                        This is your scratchpad. It is only visible to you and is persisted only in this browser. It's a
                        great place to gather ideas before turning into a saved Notebook!
                    </LemonBanner>
                ) : null}

                <div className="flex flex-1 justify-center">
                    <NotebookSidebar expanded={editable && !isExpanded} />
                    <div className={clsx(isExpanded && 'flex flex-1')}>
                        <Editor
                            initialContent={content}
                            onCreate={setEditor}
                            onUpdate={onEditorUpdate}
                            onSelectionUpdate={onEditorSelectionUpdate}
                            placeholder={({ node }: { node: any }) => {
                                if (node.type.name === 'heading' && node.attrs.level === 1) {
                                    return `Untitled - maybe.. "${headingPlaceholder}"`
                                }

                                if (node.type.name === 'heading') {
                                    return `Heading ${node.attrs.level}`
                                }

                                return ''
                            }}
                        />
                    </div>
                    <NotebookSidebar className="NotebookSettings__portal" expanded={editable && !isExpanded} />
                </div>
            </div>
        </BindLogic>
    )
}

const NotebookSidebar = ({ className, expanded }: { className?: string; expanded: boolean }): JSX.Element => {
    return <div className={clsx(className, expanded ? 'flex flex-1' : null)} />
}
