import { useValues } from 'kea'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { CodeEditor, CodeEditorProps } from 'lib/monaco/CodeEditor'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'

import { HogQLQuery } from '~/queries/schema'

import { editorSizingLogic } from './editorSizingLogic'

interface QueryPaneProps {
    queryInput: string
    promptError: string | null
    codeEditorProps: Partial<CodeEditorProps>
    sourceQuery: HogQLQuery
}

export function QueryPane(props: QueryPaneProps): JSX.Element {
    const { queryPaneHeight, queryPaneResizerProps } = useValues(editorSizingLogic)

    return (
        <>
            <div
                className="relative flex flex-col w-full bg-bg-3000"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    height: `${queryPaneHeight}px`,
                }}
                ref={queryPaneResizerProps.containerRef}
            >
                <div className="flex-1">
                    <AutoSizer>
                        {({ height, width }) => (
                            <CodeEditor
                                className="border"
                                language="hogQL"
                                value={props.queryInput}
                                sourceQuery={props.sourceQuery}
                                height={height}
                                width={width}
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
                <Resizer {...queryPaneResizerProps} />
            </div>
        </>
    )
}
