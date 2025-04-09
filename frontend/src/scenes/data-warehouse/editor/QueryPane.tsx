import { IconCheck, IconX } from '@posthog/icons'
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
    onRun?: () => void
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
                                props.onAccept?.()
                                props.onRun?.()
                            }}
                            tooltipPlacement="top"
                            size="small"
                        >
                            Accept & run
                        </LemonButton>
                        <LemonButton
                            type="tertiary"
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
                )}
                <Resizer {...queryPaneResizerProps} />
            </div>
        </>
    )
}
