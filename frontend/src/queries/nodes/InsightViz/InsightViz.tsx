import { useEffect, useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { InsightsNav } from 'scenes/insights/InsightsNav'
import { ItemMode } from '~/types'
import { isFunnelsQuery } from '~/queries/utils'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'
import { InsightQueryNode, InsightVizNode } from '../../schema'

import { InsightContainer } from './InsightContainer'
import { EditorFilters } from './EditorFilters'

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
        if (response && !hasDashboardItemId) {
            setInsight(
                {
                    ...insight,
                    result: response.result,
                    next: response.next,
                    timezone: response.timezone,
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
            {insightMode === ItemMode.Edit && <InsightsNav />}
            <div
                className={clsx('insight-wrapper', {
                    'insight-wrapper--singlecolumn': isFunnels,
                })}
            >
                <EditorFilters query={query.source} setQuery={setQuerySource} />

                <div className="insights-container" data-attr="insight-view">
                    <InsightContainer insightMode={insightMode} />
                </div>

                <div>
                    <h4>Query</h4>
                    <pre>{JSON.stringify(query, null, 2)}</pre>
                </div>
            </div>
        </BindLogic>
    )
}
