import { IconCheck, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import MaxTool from 'scenes/max/MaxTool'

import { HogQLQuery } from '~/queries/schema/schema-general'

import { editorSizingLogic } from './editorSizingLogic'
import { multitabEditorLogic } from './multitabEditorLogic'

interface QueryPaneProps {
    queryInput: string
    promptError: string | null
    codeEditorProps: Partial<CodeEditorProps>
    sourceQuery: HogQLQuery
    originalValue?: string
    onRun?: () => void
}

export function QueryPane(props: QueryPaneProps): JSX.Element {
    const { queryPaneHeight, queryPaneResizerProps } = useValues(editorSizingLogic)
    const {
        setSuggestedQueryInput,
        onAcceptSuggestedQueryInput,
        onRejectSuggestedQueryInput,
        reportAIQueryPromptOpen,
    } = useActions(multitabEditorLogic)
    const { acceptText, rejectText, diffShowRunButton } = useValues(multitabEditorLogic)

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
                <div className="relative flex flex-col w-full">
                    <div className="flex-1" data-attr="hogql-query-editor">
                        <AutoSizer>
                            {({ height, width }) => (
                                <CodeEditor
                                    language="hogQL"
                                    value={props.queryInput}
                                    sourceQuery={props.sourceQuery}
                                    height={height}
                                    width={width}
                                    originalValue={props.originalValue}
                                    {...props.codeEditorProps}
                                    options={{
                                        minimap: {
                                            enabled: false,
                                        },
                                        wordWrap: 'on',
                                        // Overscroll needed when Accept/Reject buttons are shown, so that they don't obscure the query
                                        scrollBeyondLastLine: !!props.originalValue,
                                        automaticLayout: true,
                                        fixedOverflowWidgets: true,
                                        suggest: {
                                            showInlineDetails: true,
                                        },
                                        quickSuggestionsDelay: 300,
                                    }}
                                />
                            )}
                        </AutoSizer>
                    </div>
                    <div className="absolute bottom-6 right-4">
                        <MaxTool
                            name="generate_hogql_query"
                            displayName="Write and tweak SQL"
                            description="Max can write and tweak SQL queries for you"
                            context={{
                                current_query: props.queryInput,
                            }}
                            callback={(toolOutput: string) => {
                                setSuggestedQueryInput(toolOutput, 'max_ai')
                            }}
                            suggestions={[]}
                            onMaxOpen={() => {
                                reportAIQueryPromptOpen()
                            }}
                            introOverride={{
                                headline: 'What data do you want to analyze?',
                                description: 'Let me help you quickly write SQL, and tweak it.',
                            }}
                        >
                            <div className="relative" />
                        </MaxTool>
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
