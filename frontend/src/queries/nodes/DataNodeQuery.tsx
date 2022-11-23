import MonacoEditor from '@monaco-editor/react'
import { useEffect, useState } from 'react'
import { query as runQuery } from '../query'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { Node } from '~/queries/schema'

interface DataNodeQueryProps {
    query: Node
}

/** Default renderer for data nodes. Display the JSON in a Monaco editor.  */
export function DataNodeQuery({ query }: DataNodeQueryProps): JSX.Element {
    const [response, setResponse] = useState<string>('Loading...')

    useEffect(() => {
        // The simplest thing for now.
        async function fetchIt(): Promise<void> {
            try {
                const resp = await runQuery(query)
                setResponse(JSON.stringify(resp, null, 2))
            } catch (e: any) {
                setResponse(`Error: ${e.message}`)
            }
        }
        void fetchIt()
    }, [JSON.stringify(query)])

    return (
        <AutoSizer disableWidth>
            {({ height }) => (
                <MonacoEditor
                    theme="vs-light"
                    className="border"
                    language={'json'}
                    value={response}
                    height={Math.max(height, 300)}
                />
            )}
        </AutoSizer>
    )
}
