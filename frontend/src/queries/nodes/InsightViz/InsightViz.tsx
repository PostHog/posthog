import { useEffect, useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import clsx from 'clsx'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { InsightsNav } from 'scenes/insights/InsightsNav'
import { InsightLogicProps, ItemMode } from '~/types'
import { isFunnelsQuery } from '~/queries/utils'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'
import { InsightQueryNode, InsightVizNode } from '../../schema'

import { InsightContainer } from './InsightContainer'
import { EditorFilters } from './EditorFilters'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
}

let uniqueNode = 0

export function InsightViz({ query, setQuery }: InsightVizProps): JSX.Element {
    const [key] = useState(() => `InsightViz.${uniqueNode++}`)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key,
    }

    const logic = insightLogic({ dashboardItemId: query.insightId || 'new' })
    const { insightProps } = useValues(logic)
    const insightDataProps = { ...insightProps, ...dataNodeLogicProps }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={insightDataLogic} props={insightDataProps}>
                <InsightVizInner />
            </BindLogic>
        </BindLogic>
    )
}

function InsightVizInner(): JSX.Element {
    const { response, insight, query } = useValues(insightDataLogic)
    const { setQuery } = useActions(insightDataLogic)
    // const { insight } = useValues(insightLogic(insightProps))
    // const { setInsight, setLastRefresh } = useActions(insightLogic(insightProps))

    const { insightMode } = useValues(insightSceneLogic) // TODO: Tight coupling -- remove or make optional

    // TODO: use connected logic instead of useEffect?
    // useEffect(() => {
    //     const typedResponse: Record<string, any> | undefined | null = response
    //     if (typedResponse) {
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
        <>
            {insightMode === ItemMode.Edit && <InsightsNav />}
            <div
                className={clsx('insight-wrapper', {
                    'insight-wrapper--singlecolumn': isFunnels,
                })}
            >
                <EditorFilters query={query.source} setQuery={setQuerySource} showing={insightMode === ItemMode.Edit} />

                {/* <div className="insights-container" data-attr="insight-view">
                    <InsightContainer insightMode={insightMode} />
                </div> */}
            </div>
        </>
    )
}
