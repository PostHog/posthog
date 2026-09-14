import './Notebook.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect } from 'react'

import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { NotebookLogicProps, notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { SCRATCHPAD_NOTEBOOK } from '~/models/notebooksModel'

import { MarkdownNotebookV2 } from './MarkdownNotebookV2Renderer'
import { NotebookColumnLeft } from './NotebookColumnLeft'
import { NotebookColumnRight } from './NotebookColumnRight'
import { NotebookHistoryWarning } from './NotebookHistory'
import { NotebookLoadingState } from './NotebookLoadingState'
import { NotebookMergeConflictDetails } from './NotebookMergeConflictDetails'
import { notebookSettingsLogic } from './notebookSettingsLogic'

// Counts mounted notebooks so the <body> marker class survives overlapping mounts
// (e.g. one in the scene and one in the side panel)
let markdownNotebookMountCount = 0

export type NotebookProps = NotebookLogicProps & {
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
    const { notebook, notebookLoading, isEditable, isTemplate, notebookMissing } = useValues(logic)
    const { duplicateNotebook, loadNotebook, setEditable, setLocalContent, setContainerSize } = useActions(logic)
    const { isMarkdownExpanded } = useValues(notebookSettingsLogic)

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

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        1000: 'medium',
    })

    useEffect(() => {
        setContainerSize(size as 'small' | 'medium')
    }, [size]) // oxlint-disable-line exhaustive-deps

    // Marker class replacing `body:has(.Notebook--markdown-v2)` in Notebook.scss: a near-root
    // `:has()` anchor makes every DOM class change cost a whole-document style recalc in Blink
    useLayoutEffect(() => {
        if (++markdownNotebookMountCount === 1) {
            document.body.classList.add('has-markdown-v2-notebook')
        }
        return () => {
            if (--markdownNotebookMountCount === 0) {
                document.body.classList.remove('has-markdown-v2-notebook')
            }
        }
    }, [])

    return (
        <BindLogic logic={notebookLogic} props={logicProps}>
            {!notebook && notebookLoading ? (
                <NotebookLoadingState />
            ) : notebookMissing ? (
                <NotFound object="notebook" />
            ) : (
                <div
                    className={clsx(
                        'Notebook',
                        !isMarkdownExpanded && 'Notebook--compact',
                        isMarkdownExpanded && 'Notebook--expanded',
                        mode && `Notebook--${mode}`,
                        size === 'small' && `Notebook--single-column`,
                        isEditable && 'Notebook--editable',
                        'Notebook--markdown-v2',
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

                    <div className="Notebook_content">
                        <NotebookColumnLeft />
                        <ErrorBoundary>
                            <MarkdownNotebookV2
                                debugOpen={markdownSourceOpen}
                                onDebugOpenChange={onMarkdownSourceOpenChange}
                            />
                        </ErrorBoundary>
                        <NotebookColumnRight />
                    </div>
                </div>
            )}
        </BindLogic>
    )
}
