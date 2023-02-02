import MonacoEditor from '@monaco-editor/react'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { DataNode as DataNodeType, DataTableNode, Node } from '~/queries/schema'
import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { InlineEditorButton } from '~/queries/nodes/Node/InlineEditorButton'

interface DataNodeProps {
    query: DataNodeType
    setQuery?: (query: DataTableNode) => void
}

let uniqueNode = 0

/** Default renderer for data nodes. Display the JSON in a Monaco editor.  */
export function DataNode(props: DataNodeProps): JSX.Element {
    const [key] = useState(() => `DataNode.${uniqueNode++}`)
    const logic = dataNodeLogic({ ...props, key })
    const { response, responseErrorObject, responseLoading } = useValues(logic)

    return (
        <div className="relative">
            <div className="absolute right-0 z-10 p-1 mr-3">
                <InlineEditorButton query={props.query} setQuery={props.setQuery as (node: Node) => void} />
            </div>
            {responseLoading ? (
                <div className="text-2xl">
                    <Spinner />
                </div>
            ) : (
                <AutoSizer disableWidth>
                    {({ height }) => (
                        <MonacoEditor
                            theme="vs-light"
                            className="border"
                            language={'json'}
                            value={JSON.stringify(response ?? responseErrorObject, null, 2)}
                            height={Math.max(height, 300)}
                        />
                    )}
                </AutoSizer>
            )}
        </div>
    )
}
