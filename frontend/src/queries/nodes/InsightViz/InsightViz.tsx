import { BindLogic, useValues } from 'kea'
import clsx from 'clsx'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { isFunnelsQuery } from '~/queries/utils'

import { dataNodeLogic, DataNodeLogicProps } from '../DataNode/dataNodeLogic'
import { InsightVizNode } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { InsightContainer } from './InsightContainer'
import { EditorFilters } from './EditorFilters'
import { InsightLogicProps, ItemMode } from '~/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getCachedResults } from './utils'
import { useState } from 'react'

import './Insight.scss'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

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
    }

    const { insightMode } = useValues(insightSceneLogic)

    const isFunnels = isFunnelsQuery(query.source)

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
                        className={clsx('insight-wrapper', {
                            'insight-wrapper--singlecolumn': isFunnels,
                        })}
                    >
                        {!readOnly && (
                            <EditorFilters query={query.source} showing={showingFilters} embedded={embedded} />
                        )}

                        <div className="insights-container ph-no-capture" data-attr="insight-view">
                            <InsightContainer
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
