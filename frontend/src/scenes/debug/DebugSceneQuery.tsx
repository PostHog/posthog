import { useValues } from 'kea'
import { HogQLDebug } from 'scenes/debug/HogQLDebug'
import { Modifiers } from 'scenes/debug/Modifiers'
import { QueryTabs } from 'scenes/debug/QueryTabs'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { DataNode, HogQLQuery, Node } from '~/queries/schema'
import { isDataTableNode, isInsightVizNode } from '~/queries/utils'

interface DebugSceneQueryProps {
    queryKey: `new-${string}`
    query: string
    setQuery: (query: string) => void
}

export function DebugSceneQuery({ query, setQuery, queryKey }: DebugSceneQueryProps): JSX.Element {
    let parsed: Record<string, any> | null = null
    try {
        parsed = JSON.parse(query)
    } catch (e) {
        // do nothing
    }
    const dataNode =
        parsed && (isInsightVizNode(parsed as Node) || isDataTableNode(parsed as Node)) ? parsed.source : parsed

    const dataNodeKey = insightVizDataNodeKey({ dashboardItemId: queryKey })
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: dataNode as DataNode,
        key: dataNodeKey,
        dataNodeCollectionId: queryKey,
        modifiers: { debug: true },
    }
    const { response } = useValues(dataNodeLogic(dataNodeLogicProps))

    return (
        <>
            {parsed && parsed?.kind === 'HogQLQuery' ? (
                <HogQLDebug
                    queryKey={queryKey}
                    query={parsed as HogQLQuery}
                    setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                />
            ) : (
                <div className="space-y-4">
                    <QueryEditor
                        query={query}
                        setQuery={setQuery}
                        aboveButton={
                            <Modifiers
                                setQuery={
                                    parsed?.source
                                        ? (query) => setQuery(JSON.stringify({ ...parsed, source: query }, null, 2))
                                        : (query) => setQuery(JSON.stringify(query, null, 2))
                                }
                                query={parsed?.source ?? parsed}
                                response={response}
                            />
                        }
                    />
                    {parsed ? (
                        <QueryTabs
                            query={parsed as Node}
                            queryKey={queryKey}
                            response={response}
                            setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                        />
                    ) : null}
                </div>
            )}
        </>
    )
}
