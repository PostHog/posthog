import { useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { OpenEditorButton } from '~/queries/nodes/Node/OpenEditorButton'
import { AnyResponseType, DataNode as DataNodeType, DataTableNode } from '~/queries/schema'

interface DataNodeProps {
    query: DataNodeType
    setQuery?: (query: DataTableNode) => void
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
}

let uniqueNode = 0

/** Default renderer for data nodes. Display the JSON in a Monaco editor.  */
export function DataNode(props: DataNodeProps): JSX.Element {
    const [key] = useState(() => `DataNode.${uniqueNode++}`)
    const logic = dataNodeLogic({ ...props, key, cachedResults: props.cachedResults, dataNodeCollectionId: key })
    const { response, responseLoading, responseErrorObject } = useValues(logic)

    return (
        <div className="relative">
            <div className="absolute right-0 z-10 p-1 mr-3">
                <OpenEditorButton query={props.query} />
            </div>
            {responseLoading ? (
                <div className="text-2xl">
                    <Spinner />
                </div>
            ) : (
                <AutoSizer disableWidth>
                    {({ height }) => (
                        <CodeEditor
                            className="border"
                            language="json"
                            value={JSON.stringify(response ?? responseErrorObject, null, 2)}
                            height={Math.max(height, 300)}
                        />
                    )}
                </AutoSizer>
            )}
        </div>
    )
}
