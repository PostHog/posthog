import { useActions, useValues } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'

import { AutoSizer } from 'lib/components/AutoSizer'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'

import { HogQLQuery } from '~/queries/schema/schema-general'

import { editorSizingLogic } from './editorSizingLogic'
import { sqlEditorLogic } from './sqlEditorLogic'

interface QueryPaneProps {
    queryInput: string
    promptError: string | null
    codeEditorProps: Partial<CodeEditorProps>
    sourceQuery: HogQLQuery
    originalValue?: string
    onRun?: () => void
    editorVimModeEnabled?: boolean
}

export function QueryPane(props: QueryPaneProps): JSX.Element {
    const { queryPaneHeight, queryPaneResizerProps } = useValues(editorSizingLogic)
    const { onAcceptSuggestedQueryInput, onRejectSuggestedQueryInput } = useActions(sqlEditorLogic)
    const { acceptText, rejectText, diffShowRunButton } = useValues(sqlEditorLogic)

    return (
        <>
            <div
                className="relative flex flex-row w-full bg-primary"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    height: `${queryPaneHeight}px`,
                }}
                ref={queryPaneResizerProps.containerRef}
            >
                <div className="relative flex flex-col w-full min-h-0">
                    <div className="flex-1 min-h-0" data-attr="hogql-query-editor">
                        <AutoSizer
                            renderProp={({ height, width }) =>
                                height && width ? (
                                    <CodeEditor
                                        language="hogQL"
                                        value={props.queryInput}
                                        sourceQuery={props.sourceQuery}
                                        height={height}
                                        width={width}
                                        originalValue={props.originalValue}
                                        enableVimMode={props.editorVimModeEnabled}
                                        {...props.codeEditorProps}
                                        autoFocus={true}
                                        options={{
                                            minimap: {
                                                enabled: false,
                                            },
                                            wordWrap: 'on',
                                            scrollBeyondLastLine: !!props.originalValue,
                                            automaticLayout: true,
                                            fixedOverflowWidgets: true,
                                            suggest: {
                                                showInlineDetails: true,
                                            },
                                            quickSuggestionsDelay: 300,
                                        }}
                                    />
                                ) : null
                            }
                        />
                    </div>
                    {props.originalValue && (
                        <div
                            className="absolute flex gap-1 bg-bg-light rounded border py-1 px-1.5 z-10 left-1/2 -translate-x-1/2 bottom-4 whitespace-nowrap"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)' }}
                        >
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
                    )}
                </div>
                <Resizer {...queryPaneResizerProps} />
            </div>
        </>
    )
}
