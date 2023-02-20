import { useEffect } from 'react'
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
import { InsightLogicProps, ItemMode } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

/** The key for the dataNodeLogic mounted by an InsightViz for insight of insightProps */
export const insightVizDataNodeKey = (insightProps: InsightLogicProps): string => {
    return `InsightViz.${keyForInsightLogicProps('new')(insightProps)}`
}

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
}

export function InsightViz({ query, setQuery }: InsightVizProps): JSX.Element {
    // get values and actions from bound insight logic
    const { insightProps, insight, hasDashboardItemId } = useValues(insightLogic)
    const { setInsight, setLastRefresh } = useActions(insightLogic)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key: insightVizDataNodeKey(insightProps) }
    const { response, lastRefresh } = useValues(dataNodeLogic(dataNodeLogicProps))

    const { insightMode } = useValues(insightSceneLogic) // TODO: Tight coupling -- remove or make optional

    // useEffect(() => {
    //     // TODO: this is hacky - we prevent overwriting the insight in case
    //     // of a saved insight. instead we should handle loading a saved insight
    //     // in a query as well. needs discussion around api and node schema.
    //     const typedResponse: Record<string, any> | undefined | null = response
    //     if (typedResponse && !hasDashboardItemId) {
    //         setInsight(
    //             {
    //                 ...insight,
    //                 result: typedResponse.result,
    //                 next: typedResponse.next,
    //                 timezone: typedResponse.timezone,
    //                 filters: queryNodeToFilter(query.source),
    //             },
    //             {}
    //         )
    //         setLastRefresh(lastRefresh)
    //     }
    // }, [response])

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
                <EditorFilters query={query.source} setQuery={setQuerySource} showing={insightMode === ItemMode.Edit} />

                <div className="insights-container" data-attr="insight-view">
                    <InsightContainer insightMode={insightMode} />
                </div>
            </div>
        </BindLogic>
    )
}
