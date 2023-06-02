import { BindLogic, useValues } from 'kea'
import clsx from 'clsx'
import equal from 'fast-deep-equal'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { isFunnelsQuery } from '~/queries/utils'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { InsightQueryNode, InsightVizNode, QueryContext } from '../../schema'

import { InsightContainer } from './InsightContainer'
import { EditorFilters } from './EditorFilters'
import { InsightLogicProps, InsightModel, ItemMode } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { filtersToQueryNode } from '../InsightQuery/utils/filtersToQueryNode'

const getCachedResults = (
    cachedInsight: Partial<InsightModel> | undefined | null,
    query: InsightQueryNode
): Partial<InsightModel> | undefined => {
    if (
        !cachedInsight ||
        cachedInsight.result === null ||
        cachedInsight.result === undefined ||
        cachedInsight.filters === undefined
    ) {
        return undefined
    }

    // only set the cached result when the filters match the currently set ones
    const cachedQueryNode = filtersToQueryNode(cachedInsight.filters)
    if (!equal(cachedQueryNode, query)) {
        return undefined
    }

    return cachedInsight
}

/** The key for the dataNodeLogic mounted by an InsightViz for insight of insightProps */
export const insightVizDataNodeKey = (insightProps: InsightLogicProps): string => {
    return `InsightViz.${keyForInsightLogicProps('new')(insightProps)}`
}

type InsightVizProps = {
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
    context?: QueryContext
}

export function InsightViz({ query, setQuery, context }: InsightVizProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(insightProps.cachedInsight, query.source),
    }

    const { insightMode } = useValues(insightSceneLogic)

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
                    <InsightContainer insightMode={insightMode} context={context} />
                </div>
            </div>
        </BindLogic>
    )
}
