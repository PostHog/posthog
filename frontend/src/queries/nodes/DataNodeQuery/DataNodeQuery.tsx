import MonacoEditor from '@monaco-editor/react'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { Node } from '~/queries/schema'
import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/dataNodeLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'

interface DataNodeQueryProps {
    query: Node
}

let i = 0

/** Default renderer for data nodes. Display the JSON in a Monaco editor.  */
export function DataNodeQuery(props: DataNodeQueryProps): JSX.Element {
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
                    height={Math.max(height - 62, 300)}
                />
            )}
        </AutoSizer>
    )
}
