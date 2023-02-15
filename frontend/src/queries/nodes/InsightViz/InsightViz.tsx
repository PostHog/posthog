import { useEffect, useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { isFunnelsQuery } from '~/queries/utils'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'
import { InsightQueryNode, InsightVizNode } from '../../schema'

import { InsightContainer } from './InsightContainer'
import { EditorFilters } from './EditorFilters'
import { ItemMode } from '~/types'

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
}

let uniqueNode = 0

export function InsightViz({ query, setQuery }: InsightVizProps): JSX.Element {
    // TODO use same key as insight props
    const [key] = useState(() => `InsightViz.${uniqueNode++}`)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key }
    const { response, lastRefresh } = useValues(dataNodeLogic(dataNodeLogicProps))

    // get values and actions from bound insight logic
    const { insight, hasDashboardItemId } = useValues(insightLogic)
    const { setInsight, setLastRefresh } = useActions(insightLogic)

    const { insightMode } = useValues(insightSceneLogic) // TODO: Tight coupling -- remove or make optional

    // TODO: use connected logic instead of useEffect?
    useEffect(() => {
        // TODO: this is hacky - we prevent overwriting the insight in case
        // of a saved insight. instead we should handle loading a saved insight
        // in a query as well. needs discussion around api and node schema.
        const typedResponse: Record<string, any> | undefined | null = response
        if (typedResponse && !hasDashboardItemId) {
            setInsight(
                {
                    ...insight,
                    result: typedResponse.result,
                    next: typedResponse.next,
                    timezone: typedResponse.timezone,
                    filters: queryNodeToFilter(query.source),
                },
                {}
            )
            setLastRefresh(lastRefresh)
        }
    }, [response])

    const isFunnels = isFunnelsQuery(query.source)

    const setQuerySource = (source: InsightQueryNode): void => {
        setQuery?.({ ...query, source })
    }

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <div
                className={clsx('insight-wrapper', {
                    'insight-wrapper--singlecolumn': isFunnels,
                })}
            >
                {query.showEditorPanel && (
                    <EditorFilters
                        query={query.source}
                        setQuery={setQuerySource}
                        showing={insightMode === ItemMode.Edit}
                    />
                )}

                <div className="insights-container" data-attr="insight-view">
                    <InsightContainer insightMode={insightMode} />
                </div>
            </div>
        </BindLogic>
    )
}
