import './InsightViz.scss'

import clsx from 'clsx'
import { BindLogic, BuiltLogic, LogicWrapper, useValues } from 'kea'
import { useState } from 'react'

// InsightViz renders the .InsightCard__viz wrapper whose styles live in InsightCard.scss.
// Import it here so the viz is sized correctly wherever it renders, not only inside an InsightCard.
import 'lib/components/Cards/InsightCard/InsightCard.scss'
import { analysisEngagementKey, resolveAnalysisSurface, useAnalysisEngagement } from 'lib/hooks/useAnalysisEngagement'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { AnyResponseType, DashboardFilter, HogQLVariable, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { hasNonEmptyQueryResponse } from '~/queries/utils'
import { InsightLogicProps } from '~/types'

import { DataNodeLogicProps, dataNodeLogic } from '../DataNode/dataNodeLogic'
import { EditorFilters } from './EditorFilters'
import { InsightVizDisplay } from './InsightVizDisplay'
import { insightVizDataCollectionId, insightVizDataNodeKey } from './insightVizKeys'
import { getCachedResults } from './utils'

export { insightVizDataCollectionId, insightVizDataNodeKey } from './insightVizKeys'

type InsightVizProps = {
    uniqueKey?: string | number
    query: InsightVizNode
    setQuery: (node: InsightVizNode) => void
    context?: QueryContext<InsightVizNode>
    readOnly?: boolean
    editMode?: boolean
    embedded?: boolean
    inSharedMode?: boolean
    filtersOverride?: DashboardFilter | null
    variablesOverride?: Record<string, HogQLVariable> | null
    /** Attach ourselves to another logic, such as the scene logic */
    attachTo?: BuiltLogic | LogicWrapper
    cachedResults?: AnyResponseType
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
    attachTo,
    editMode,
    cachedResults,
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
        cachedResults: cachedResults || getCachedResults(insightProps.cachedInsight, query.source),
        doNotLoad: insightProps.doNotLoad,
        onData: insightProps.onData,
        loadPriority: insightProps.loadPriority,
        dataNodeCollectionId: insightVizDataCollectionId(insightProps, vizKey),
        filtersOverride,
        variablesOverride,
        limitContext: context?.limitContext,
    }

    const showIfFull = !!query.full
    const disableHeader = embedded || !(query.showHeader ?? showIfFull)
    const disableTable = embedded || !(query.showTable ?? showIfFull)
    const disableCorrelationTable = embedded || !(query.showCorrelationTable ?? showIfFull)
    const disableLastComputation = embedded || !(query.showLastComputation ?? showIfFull)
    const disableLastComputationRefresh = embedded || !(query.showLastComputationRefresh ?? showIfFull)
    const showingFilters = query.showFilters ?? editMode ?? false
    const showingResults = query.showResults ?? true
    const isEmbedded = embedded || (query.embedded ?? false)

    const display = (
        <InsightVizDisplay
            editMode={editMode}
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

    useAttachedLogic(dataNodeLogic(dataNodeLogicProps), attachTo)
    useAttachedLogic(insightLogic(insightProps as InsightLogicProps) as BuiltLogic, attachTo)
    useAttachedLogic(insightDataLogic(insightProps as InsightLogicProps), attachTo)
    useAttachedLogic(insightVizDataLogic(insightProps as InsightLogicProps), attachTo)

    const { insight } = useValues(insightLogic(insightProps as InsightLogicProps))
    const { insightData, insightDataLoading, erroredQueryId, timedOutQueryId, validationError } = useValues(
        insightVizDataLogic(insightProps as InsightLogicProps)
    )

    // Only a settled, non-empty result counts. Shared and exported views are left out because they
    // render without a signed-in user, and an export renders in PostHog's own headless browser.
    const resultIsAnalyzable =
        !isSharedView() &&
        !insightDataLoading &&
        !erroredQueryId &&
        !timedOutQueryId &&
        !validationError &&
        hasNonEmptyQueryResponse(insightData)

    const engagementRef = useAnalysisEngagement(
        resultIsAnalyzable
            ? {
                  key: analysisEngagementKey(insight?.short_id, query.source),
                  surface: resolveAnalysisSurface(context, insightProps.dashboardId),
                  query,
                  insightShortId: insight?.short_id ?? null,
                  dashboardId: insightProps.dashboardId ?? null,
                  isSaved: insight?.saved,
                  createdByUuid: insight?.created_by?.uuid ?? null,
              }
            : null
    )

    return (
        <ErrorBoundary exceptionProps={{ feature: 'InsightViz' }}>
            <BindLogic logic={insightLogic} props={insightProps}>
                <BindLogic logic={insightDataLogic} props={insightProps}>
                    <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                        <BindLogic logic={insightVizDataLogic} props={insightProps}>
                            <div
                                ref={engagementRef}
                                className={
                                    !isEmbedded
                                        ? clsx('InsightViz InsightViz--horizontal', {
                                              '!gap-4': editMode,
                                              '!gap-0': !editMode,
                                              'flex-1': editMode,
                                          })
                                        : 'InsightCard__viz'
                                }
                            >
                                <EditorFilters
                                    query={query.source}
                                    showing={!readOnly && showingFilters}
                                    embedded={isEmbedded}
                                />
                                {!isEmbedded ? (
                                    <div className="flex-1 max-h-full overflow-auto">{display}</div>
                                ) : (
                                    display
                                )}
                            </div>
                        </BindLogic>
                    </BindLogic>
                </BindLogic>
            </BindLogic>
        </ErrorBoundary>
    )
}
