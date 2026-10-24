import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheck, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { AutoSizer } from 'lib/components/AutoSizer'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'
import { cn } from 'lib/utils/css-classes'

import { HogQLQuery } from '~/queries/schema/schema-general'

import { editorSizingLogic } from './editorSizingLogic'
import { QueryPaneFloatingBar } from './QueryPaneFloatingBar'
import { QueryPaneSaveBar } from './QueryPaneSaveBar'
import { sqlEditorLogic } from './sqlEditorLogic'

interface QueryPaneProps {
    queryInput: string
    promptError: string | null
    codeEditorProps: Partial<CodeEditorProps>
    sourceQuery: HogQLQuery
    originalValue?: string
    onRun?: () => void
    editorVimModeEnabled?: boolean
    editorVimrc?: string
    constrainHeight?: boolean
    /** Opt in to the floating save bar for the view being edited. Hosts with no view leave it off. */
    showInlineSaveBar?: boolean
    /** Saved query text to diff the edit against while typing. Unset leaves the plain editor. */
    liveDiffOriginalValue?: string
}

export function QueryPane(props: QueryPaneProps): JSX.Element {
    // A suggestion's diff and the live edit diff both render through originalValue, but only the
    // suggestion gets the accept and reject bar: the live one is saved from QueryPaneSaveBar.
    const diffOriginalValue = props.originalValue || props.liveDiffOriginalValue
    const { queryPaneHeight, queryPaneDesiredSize, queryPaneResizerProps } = useValues(editorSizingLogic)
    const { onAcceptSuggestedQueryInput, onRejectSuggestedQueryInput } = useActions(sqlEditorLogic)
    const { acceptText, rejectText, diffShowRunButton, insightLoading } = useValues(sqlEditorLogic)
    const queryLoading = insightLoading && !props.queryInput
    const editorOptions = useMemo<CodeEditorProps['options']>(
        () => ({
            minimap: {
                enabled: false,
            },
            wordWrap: 'on',
            scrollBeyondLastLine: !!diffOriginalValue,
            automaticLayout: true,
            fixedOverflowWidgets: true,
            glyphMargin: true,
            suggest: {
                showInlineDetails: true,
            },
            quickSuggestionsDelay: 300,
            readOnly: queryLoading,
        }),
        [diffOriginalValue, queryLoading]
    )
    // Without an output pane beneath it the editor owns its column, so it takes whatever height the
    // database tree gives the row rather than leaving dead space next to the schema list.
    const fillsColumn = props.constrainHeight === false

    return (
        <>
            <div
                // No min-h-0 here: Tailwind runs with `important`, so the utility would beat the
                // inline min-height that keeps the editor readable when the tree is closed.
                className={cn('relative flex flex-row w-full bg-primary', fillsColumn && 'flex-1')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    height: fillsColumn ? undefined : `${queryPaneHeight}px`,
                    minHeight: fillsColumn ? `${queryPaneHeight}px` : undefined,
                    maxHeight: !fillsColumn && queryPaneDesiredSize === null ? '35%' : undefined,
                }}
                ref={queryPaneResizerProps.containerRef}
            >
                <div className="relative flex flex-col w-full min-h-0">
                    {/*
                     * A notebook cell puts this pane in a container that the browser sizes from
                     * its content. The pane is a flex item there, so the editor inside it sets
                     * the floor the pane can reach. Monaco reports the height it already has, so
                     * a drag could only make the pane taller. The editor leaves the flow here so
                     * that `queryPaneHeight` alone sets the height.
                     */}
                    <div
                        className={cn('flex-1 min-h-0', fillsColumn && 'absolute inset-0')}
                        data-attr="hogql-query-editor"
                    >
                        <AutoSizer
                            renderProp={({ height, width }) =>
                                height && width ? (
                                    <CodeEditor
                                        language="hogQL"
                                        value={props.queryInput}
                                        sourceQuery={props.sourceQuery}
                                        height={height}
                                        width={width}
                                        originalValue={diffOriginalValue}
                                        hideOriginalLineNumbers={!props.originalValue && !!props.liveDiffOriginalValue}
                                        enableVimMode={props.editorVimModeEnabled}
                                        vimrc={props.editorVimrc}
                                        {...props.codeEditorProps}
                                        autoFocus={!queryLoading && (props.codeEditorProps.autoFocus ?? true)}
                                        options={editorOptions}
                                    />
                                ) : null
                            }
                        />
                    </div>
                    {queryLoading && (
                        <div
                            className="absolute inset-0 z-10 flex items-center justify-center gap-2 bg-primary"
                            role="status"
                        >
                            <Spinner />
                            <span>Loading query…</span>
                        </div>
                    )}
                    {props.showInlineSaveBar && !props.originalValue && <QueryPaneSaveBar />}
                    {props.originalValue && (
                        <QueryPaneFloatingBar>
                            <div className="flex gap-1 whitespace-nowrap px-1.5 py-1">
                                {!!diffShowRunButton && (
                                    <LemonButton
                                        type="primary"
                                        icon={<IconCheck color="var(--success)" />}
                                        onClick={() => {
                                            onAcceptSuggestedQueryInput(true)
                                        }}
                                        tooltipPlacement="top"
                                        size="small"
                                    >
                                        {acceptText} & run
                                    </LemonButton>
                                )}
                                <LemonButton
                                    type="tertiary"
                                    icon={<IconCheck color="var(--success)" />}
                                    onClick={() => {
                                        onAcceptSuggestedQueryInput()
                                    }}
                                    tooltipPlacement="top"
                                    size="small"
                                >
                                    {acceptText}
                                </LemonButton>
                                <LemonButton
                                    status="danger"
                                    icon={<IconX />}
                                    onClick={() => {
                                        onRejectSuggestedQueryInput()
                                    }}
                                    tooltipPlacement="top"
                                    size="small"
                                >
                                    {rejectText}
                                </LemonButton>
                            </div>
                        </QueryPaneFloatingBar>
                    )}
                </div>
                <Resizer {...queryPaneResizerProps} />
            </div>
        </>
    )
}
