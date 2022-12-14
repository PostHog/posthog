import { useState } from 'react'
import { InsightVizNode } from '../../schema'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { useValues } from 'kea'

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
}

let uniqueNode = 0

export function InsightViz({ query }: InsightVizProps): JSX.Element {
    const [key] = useState(() => `InsightViz.${uniqueNode++}`)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key }
    const {
        response,
        responseLoading,
        // canLoadNextData,
        // canLoadNewData,
        // nextDataLoading,
        // newDataLoading,
    } = useValues(dataNodeLogic(dataNodeLogicProps))

    return (
        <div>
            <h3>InsightViz</h3>
            <h4>Query</h4>
            <pre>{JSON.stringify(query, null, 2)}</pre>
            <h4>Response</h4>
            {responseLoading ? <span>Loading...</span> : <pre>{JSON.stringify(response, null, 2)}</pre>}
        </div>
    )
}
