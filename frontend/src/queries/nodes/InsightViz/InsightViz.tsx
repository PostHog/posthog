import './InsightViz.scss'

import clsx from 'clsx'
import { BindLogic } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { DashboardFilter, HogQLVariable, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { isFunnelsQuery, isRetentionQuery } from '~/queries/utils'
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
    setQuery: (node: InsightVizNode) => void
    context?: QueryContext
    readOnly?: boolean
    embedded?: boolean
    inSharedMode?: boolean
    filtersOverride?: DashboardFilter | null
    variablesOverride?: Record<string, HogQLVariable> | null
}

let uniqueNode = 0

export function InsightViz({
    uniqueKey,
    query,
    setQuery,
    context,
    readOnly,
    embedded,
    inSharedMode,
    filtersOverride,
    variablesOverride,
}: InsightVizProps): JSX.Element {
    const [key] = useState(() => `InsightViz.${uniqueKey || uniqueNode++}`)
    const insightProps =
        context?.insightProps ||
        ({
            dashboardItemId: `new-AdHoc.${key}`,
            query,
            setQuery,
            dataNodeCollectionId: key,
            filtersOverride,
            variablesOverride,
        } as InsightLogicProps<InsightVizNode>)

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
        filtersOverride,
        variablesOverride,
    }

    const isFunnels = isFunnelsQuery(query.source)
    const isHorizontalAlways = useFeatureFlag('INSIGHT_HORIZONTAL_CONTROLS')
    const isRetention = isRetentionQuery(query.source)

    const showIfFull = !!query.full
    const disableHeader = embedded || !(query.showHeader ?? showIfFull)
    const disableTable = embedded || !(query.showTable ?? showIfFull)
    const disableCorrelationTable = embedded || !(query.showCorrelationTable ?? showIfFull)
    const disableLastComputation = embedded || !(query.showLastComputation ?? showIfFull)
    const disableLastComputationRefresh = embedded || !(query.showLastComputationRefresh ?? showIfFull)
    const showingFilters =
        query.showFilters ?? (context?.insightMode === ItemMode.Edit || context?.insightMode === ItemMode.EditOnly)
    const showingResults = query.showResults ?? true
    const isEmbedded = embedded || (query.embedded ?? false)

    const display = (
        <InsightVizDisplay
            context={context}
            disableHeader={disableHeader}
            disableTable={disableTable}
            disableCorrelationTable={disableCorrelationTable}
            disableLastComputation={disableLastComputation}
            disableLastComputationRefresh={disableLastComputationRefresh}
            showingResults={showingResults}
            embedded={isEmbedded}
            inSharedMode={inSharedMode}
        />
    )

    return (
        <ErrorBoundary exceptionProps={{ feature: 'InsightViz' }}>
            <BindLogic logic={insightLogic} props={insightProps}>
                <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                    <BindLogic logic={insightVizDataLogic} props={insightProps}>
                        <div
                            className={
                                !isEmbedded
                                    ? clsx('InsightViz', {
                                          'InsightViz--horizontal': isFunnels || isRetention || isHorizontalAlways,
                                      })
                                    : 'InsightCard__viz'
                            }
                        >
                            {!readOnly && (
                                <EditorFilters query={query.source} showing={showingFilters} embedded={isEmbedded} />
                            )}
                            {context?.insightMode === ItemMode.EditOnly ? null : !isEmbedded ? (
                                <div className="flex-1 h-full overflow-auto">{display}</div>
                            ) : (
                                display
                            )}
                        </div>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </ErrorBoundary>
    )
}
