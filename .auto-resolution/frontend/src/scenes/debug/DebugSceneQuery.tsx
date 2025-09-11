import { useValues } from 'kea'

import { HogDebug } from 'scenes/debug/HogDebug'
import { HogQLDebug } from 'scenes/debug/HogQLDebug'
import { Modifiers } from 'scenes/debug/Modifiers'
import { QueryTabs } from 'scenes/debug/QueryTabs'

import { QueryEditor } from '~/queries/QueryEditor/QueryEditor'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { Node } from '~/queries/schema/schema-general'
import { isDataTableNode, isHogQLQuery, isHogQuery, isInsightVizNode } from '~/queries/utils'

interface DebugSceneQueryProps {
    queryKey: `new-${string}`
    query: string
    setQuery: (query: string) => void
}

export function DebugSceneQuery({ query, setQuery, queryKey }: DebugSceneQueryProps): JSX.Element {
    let parsed: Record<string, any> | null = null
    try {
        parsed = JSON.parse(query)
    } catch {
        // do nothing
    }
    const dataNode = parsed && (isInsightVizNode(parsed) || isDataTableNode(parsed)) ? parsed.source : (parsed as Node)

    const dataNodeKey = insightVizDataNodeKey({ dashboardItemId: queryKey })
    const modifiers = { debug: true, timings: true }
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: dataNode,
        key: dataNodeKey,
        dataNodeCollectionId: queryKey,
        modifiers,
    }
    const { response } = useValues(dataNodeLogic(dataNodeLogicProps))

    return (
        <>
            {isHogQuery(parsed) ? (
                <HogDebug
                    queryKey={queryKey}
                    query={parsed}
                    setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                    debug
                    modifiers={modifiers}
                />
            ) : isHogQLQuery(parsed) ? (
                <HogQLDebug
                    queryKey={queryKey}
                    query={parsed}
                    setQuery={(query) => setQuery(JSON.stringify(query, null, 2))}
                    modifiers={modifiers}
                />
            ) : (
                <div className="deprecated-space-y-4">
                    <QueryEditor
                        query={query}
                        setQuery={setQuery}
                        aboveButton={
                            <Modifiers
                                setQuery={
                                    parsed && 'source' in parsed && parsed?.source
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
