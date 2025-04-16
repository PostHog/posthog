import { IconCheck, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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

    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <div
                className="relative flex flex-col w-full bg-primary"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    height: `${queryPaneHeight}px`,
                }}
                ref={queryPaneResizerProps.containerRef}
            >
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
                {featureFlags[FEATURE_FLAGS.AI_HOGQL] && (
                    <div className="absolute bottom-6 right-4">
                        <MaxTool
                            name="generate_hogql_query"
                            displayName="Write and tweak SQL"
                            context={{
                                current_query: props.queryInput,
                            }}
                            callback={(toolOutput: string) => {
                                setSuggestedQueryInput(toolOutput)
                            }}
                            suggestions={[]}
                            onMaxOpen={() => {
                                reportAIQueryPromptOpen()
                            }}
                        >
                            <div className="relative" />
                        </MaxTool>
                    </div>
                )}
                {props.originalValue && (
                    <div
                        className="absolute flex gap-1 bg-bg-light rounded border py-1 px-1.5 z-10 left-1/2 -translate-x-1/2 bottom-4 whitespace-nowrap"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)' }}
                    >
                        <LemonButton
                            type="primary"
                            icon={<IconCheck color="var(--success)" />}
                            onClick={() => {
                                onAcceptSuggestedQueryInput(true)
                            }}
                            tooltipPlacement="top"
                            size="small"
                        >
                            Accept & run
                        </LemonButton>
                        <LemonButton
                            type="tertiary"
                            icon={<IconCheck color="var(--success)" />}
                            onClick={() => {
                                onAcceptSuggestedQueryInput()
                            }}
                            tooltipPlacement="top"
                            size="small"
                        >
                            Accept
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
                            Reject
                        </LemonButton>
                    </div>
                )}
                <Resizer {...queryPaneResizerProps} />
            </div>
        </>
    )
}
