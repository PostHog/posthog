import './InsightViz.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import React, { useState } from 'react'
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
export const insightVizDataNodeKey = (insightProps: InsightLogicProps<any>): string => {
    return `InsightViz.${keyForInsightLogicProps('new')(insightProps)}`
}

export const insightVizDataCollectionId = (props: InsightLogicProps<any> | undefined, fallback: string): string => {
    return props?.dataNodeCollectionId ?? props?.dashboardId?.toString() ?? props?.dashboardItemId ?? fallback
}

type InsightVizProps = {
    uniqueKey?: string | number
    query: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
    context?: QueryContext
    readOnly?: boolean
    embedded?: boolean
}

let uniqueNode = 0

export function InsightViz({ uniqueKey, query, setQuery, context, readOnly, embedded }: InsightVizProps): JSX.Element {
    const [key] = useState(() => `InsightViz.${uniqueKey || uniqueNode++}`)
    const insightProps: InsightLogicProps = context?.insightProps || {
        dashboardItemId: `new-AdHoc.${key}`,
        query,
        setQuery,
        dataNodeCollectionId: key,
    }

    if (!insightProps.setQuery && setQuery) {
        insightProps.setQuery = setQuery
    }

    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        cachedResults: getCachedResults(insightProps.cachedInsight, query.source),
        doNotLoad: insightProps.doNotLoad,
        onData: insightProps.onData,
        loadPriority: insightProps.loadPriority,
        dataNodeCollectionId: insightVizDataCollectionId(insightProps, vizKey),
    }

    const { insightMode } = useValues(insightSceneLogic)

    const isFunnels = isFunnelsQuery(query.source)
    const isHorizontalAlways = useFeatureFlag('INSIGHT_HORIZONTAL_CONTROLS')

    const showIfFull = !!query.full
    const disableHeader = embedded || !(query.showHeader ?? showIfFull)
    const disableTable = embedded || !(query.showTable ?? showIfFull)
    const disableCorrelationTable = embedded || !(query.showCorrelationTable ?? showIfFull)
    const disableLastComputation = embedded || !(query.showLastComputation ?? showIfFull)
    const disableLastComputationRefresh = embedded || !(query.showLastComputationRefresh ?? showIfFull)
    const showingFilters = query.showFilters ?? insightMode === ItemMode.Edit
    const showingResults = query.showResults ?? true
    const isEmbedded = embedded || (query.embedded ?? false)

    const Wrapper = ({ children }: { children: React.ReactElement }): JSX.Element => {
        return isEmbedded ? <>{children}</> : <div className="flex-1 h-full overflow-auto">{children}</div>
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <BindLogic logic={insightVizDataLogic} props={insightProps}>
                    <div
                        className={
                            !isEmbedded
                                ? clsx('InsightViz', {
                                      'InsightViz--horizontal': isFunnels || isHorizontalAlways,
                                  })
                                : 'InsightCard__viz'
                        }
                    >
                        {!readOnly && (
                            <EditorFilters query={query.source} showing={showingFilters} embedded={isEmbedded} />
                        )}

                        <Wrapper>
                            <InsightVizDisplay
                                insightMode={insightMode}
                                context={context}
                                disableHeader={disableHeader}
                                disableTable={disableTable}
                                disableCorrelationTable={disableCorrelationTable}
                                disableLastComputation={disableLastComputation}
                                disableLastComputationRefresh={disableLastComputationRefresh}
                                showingResults={showingResults}
                                embedded={isEmbedded}
                            />
                        </Wrapper>
                    </div>
                </BindLogic>
            </BindLogic>
        </BindLogic>
    )
}
