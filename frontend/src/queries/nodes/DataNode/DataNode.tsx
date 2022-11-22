import MonacoEditor from '@monaco-editor/react'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { DataNode as DataNodeType } from '~/queries/schema'
import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/dataNodeLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'

interface DataNodeProps {
    query: DataNodeType
}

let i = 0

/** Default renderer for data nodes. Display the JSON in a Monaco editor.  */
export function DataNode(props: DataNodeProps): JSX.Element {
    const [key] = useState(() => String(i++))
    const logic = dataNodeLogic({ ...props, key })
    const { response, responseLoading } = useValues(logic)

    return responseLoading ? (
        <Spinner />
    ) : (
        <AutoSizer disableWidth>
            {({ height }) => (
                <MonacoEditor
                    theme="vs-light"
                    className="border"
                    language={'json'}
                    value={JSON.stringify(response, null, 2)}
                    height={Math.max(height, 300)}
                />
            )}
        </AutoSizer>
    )
}
