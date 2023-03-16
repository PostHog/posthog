import MonacoEditor from '@monaco-editor/react'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { AnyResponseType, NodeKind, TimeToSeeDataNode } from '~/queries/schema'
import { useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { Trace } from './Trace/Trace'
import { TimeToSeeSessionNode } from './types'

let uniqueNode = 0

/** Default renderer for data nodes. Display the JSON in a Monaco editor.  */
export function TimeToSeeData(props: { query: TimeToSeeDataNode; cachedResults?: AnyResponseType }): JSX.Element {
    const [key] = useState(() => `TimeToSeeData.${uniqueNode++}`)
    const logic = dataNodeLogic({ query: props.query, key, cachedResults: props.cachedResults })
    const { response, responseLoading } = useValues(logic)

    if (responseLoading) {
        return (
            <div className="text-2xl">
                <Spinner />
            </div>
        )
    }

    if (!response) {
        return <div className="text-2xl">No session found.</div>
    }

    return (
        <>
            {props.query.kind === NodeKind.TimeToSeeDataSessionsJSONNode ? (
                <AutoSizer disableWidth>
                    {({ height }) => (
                        <MonacoEditor
                            theme="vs-light"
                            className="border"
                            language={'json'}
                            value={JSON.stringify(response, null, 2)}
                            height={Math.max(height, 300)}
                            loading={<Spinner />}
                        />
                    )}
                </AutoSizer>
            ) : (
                <Trace timeToSeeSession={response as TimeToSeeSessionNode} />
            )}
        </>
    )
}
