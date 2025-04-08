import { IconCheck } from '@posthog/icons'
import { IconX } from '@posthog/icons'
import { useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'

import { HogQLQuery } from '~/queries/schema/schema-general'

import { editorSizingLogic } from './editorSizingLogic'

interface QueryPaneProps {
    queryInput: string
    promptError: string | null
    codeEditorProps: Partial<CodeEditorProps>
    sourceQuery: HogQLQuery
    originalValue?: string
    onAccept?: () => void
    onReject?: () => void
}

export function QueryPane(props: QueryPaneProps): JSX.Element {
    const { queryPaneHeight, queryPaneResizerProps } = useValues(editorSizingLogic)

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
                                    scrollBeyondLastLine: false,
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
                {props.originalValue && (
                    <div
                        className="absolute"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            bottom: '16px',
                            left: '50%',
                            transform: 'translateX(-50%)',
                            zIndex: 10,
                            backgroundColor: 'white',
                            padding: '4px 6px',
                            borderRadius: '6px',
                            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
                            border: '1px solid var(--border)',
                        }}
                    >
                        <div className="flex gap-1">
                            <LemonButton
                                type="primary"
                                icon={<IconCheck color="var(--success)" />}
                                onClick={props.onAccept}
                                tooltipPlacement="top"
                                size="small"
                            >
                                Accept
                            </LemonButton>
                            <LemonButton
                                status="danger"
                                icon={<IconX />}
                                onClick={props.onReject}
                                tooltipPlacement="top"
                                size="small"
                            >
                                Reject
                            </LemonButton>
                        </div>
                    </div>
                )}
                <Resizer {...queryPaneResizerProps} />
            </div>
        </>
    )
}
