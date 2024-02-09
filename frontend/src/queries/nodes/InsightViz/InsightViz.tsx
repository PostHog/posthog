import './InsightViz.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightVizNode } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { isFunnelsQuery } from '~/queries/utils'
import { InsightLogicProps, ItemMode } from '~/types'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { EditorFilters } from './EditorFilters'
import { InsightVizDisplay } from './InsightVizDisplay'
import { getCachedResults } from './utils'

/** The key for the dataNodeLogic mounted by an InsightViz for insight of insightProps */
export const insightVizDataNodeKey = (insightProps: InsightLogicProps): string => {
    return `InsightViz.${keyForInsightLogicProps('new')(insightProps)}`
}

type InsightVizProps = {
    uniqueKey?: string | number
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
    context?: QueryContext
    readOnly?: boolean
}

let uniqueNode = 0

export function InsightViz({ uniqueKey, query, setQuery, context, readOnly }: InsightVizProps): JSX.Element {
    const [key] = useState(() => `InsightViz.${uniqueKey || uniqueNode++}`)
    const insightProps: InsightLogicProps = context?.insightProps || {
        dashboardItemId: `new-AdHoc.${key}`,
        query,
        setQuery,
    }

    if (!insightProps.setQuery && setQuery) {
        insightProps.setQuery = setQuery
    }

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(insightProps.cachedInsight, query.source),
        doNotLoad: insightProps.doNotLoad,
        onData: insightProps.onData,
        loadPriority: insightProps.loadPriority,
    }

    const { insightMode } = useValues(insightSceneLogic)

    const isFunnels = isFunnelsQuery(query.source)
    const isHorizontalAlways = useFeatureFlag('INSIGHT_HORIZONTAL_CONTROLS')

    const showIfFull = !!query.full
    const disableHeader = !(query.showHeader ?? showIfFull)
    const disableTable = !(query.showTable ?? showIfFull)
    const disableCorrelationTable = !(query.showCorrelationTable ?? showIfFull)
    const disableLastComputation = !(query.showLastComputation ?? showIfFull)
    const disableLastComputationRefresh = !(query.showLastComputationRefresh ?? showIfFull)
    const showingFilters = query.showFilters ?? insightMode === ItemMode.Edit
    const showingResults = query.showResults ?? true
    const embedded = query.embedded ?? false

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <BindLogic logic={insightVizDataLogic} props={insightProps}>
                    <div
                        className={clsx('InsightViz', {
                            'InsightViz--horizontal': isFunnels || isHorizontalAlways,
                        })}
                    >
                        {!readOnly && (
                            <EditorFilters query={query.source} showing={showingFilters} embedded={embedded} />
                        )}

                        <div className="flex-1 h-full overflow-x-hidden">
                            <InsightVizDisplay
                                insightMode={insightMode}
                                context={context}
                                disableHeader={disableHeader}
                                disableTable={disableTable}
                                disableCorrelationTable={disableCorrelationTable}
                                disableLastComputation={disableLastComputation}
                                disableLastComputationRefresh={disableLastComputationRefresh}
                                showingResults={showingResults}
                                embedded={embedded}
                            />
                        </div>
                    </div>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
