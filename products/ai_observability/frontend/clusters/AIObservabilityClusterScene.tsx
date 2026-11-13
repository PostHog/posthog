import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconChevronLeft, IconChevronRight, IconQuestion } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton, Spinner, Tooltip } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { groupsModel } from '~/models/groupsModel'
import { ProductKey } from '~/queries/schema/schema-general'

import { TraceDrawerHost } from '../redesign/trace/TraceDrawerHost'
import { TraceDrawerRowsSync } from '../redesign/trace/TraceDrawerRowsHost'
import { ClusterDescription } from './ClusterDescriptionComponents'
import { ClusterDetailLogicProps, clusterDetailLogic } from './clusterDetailLogic'
import { ClusterDetailMetrics } from './ClusterDetailMetrics'
import { ClusterDetailScatterPlot } from './ClusterDetailScatterPlot'
import { ClusterItemsTable } from './ClusterItemsTable'
import { toClusterTraceDrawerRow } from './clusterTraceDrawerRow'

export const scene: SceneExport<ClusterDetailLogicProps> = {
    component: AIObservabilityClusterScene,
    logic: clusterDetailLogic,
    productKey: ProductKey.AI_OBSERVABILITY,
    paramsToProps: ({ params: { runId, clusterId } }) => ({
        runId: runId ? decodeURIComponent(runId) : '',
        clusterId: clusterId ? parseInt(clusterId, 10) : 0,
    }),
}

export function AIObservabilityClusterScene(): JSX.Element {
    const {
        cluster,
        clusterDataLoading,
        clusteringLevel,
        totalTraces,
        unfilteredTotalTraces,
        totalPages,
        currentPage,
        paginatedTracesWithSummaries,
        traceSummariesLoading,
        windowStart,
        windowEnd,
        propertyFilters,
        shouldFilterTestAccounts,
        filteredItemIdsLoading,
        itemMetrics,
        clusterData,
    } = useValues(clusterDetailLogic)
    const { setPage, setPropertyFilters, setShouldFilterTestAccounts } = useActions(clusterDetailLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const drawerRows = useMemo(
        () =>
            paginatedTracesWithSummaries
                .map((item) => toClusterTraceDrawerRow(item, clusteringLevel))
                .filter((row) => row !== null),
        [paginatedTracesWithSummaries, clusteringLevel]
    )

    if (clusterDataLoading) {
        return (
            <SceneContent>
                <LemonSkeleton className="h-8 w-1/3" />
                <LemonSkeleton className="h-96 w-full" />
            </SceneContent>
        )
    }
    if (!cluster) {
        return <NotFound object="cluster" />
    }

    const itemLabel =
        clusteringLevel === 'generation' ? 'Generations' : clusteringLevel === 'evaluation' ? 'Evaluations' : 'Traces'
    const backUrl = urls.aiObservabilityClusters(clusterData?.runId)

    return (
        <SceneContent>
            <SceneTitleSection
                name={cluster.title}
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    todayRailNav ? (
                        <Button
                            variant="outline"
                            render={<LinkPrimitive to={backUrl} />}
                            data-attr="clusters-back-button"
                        >
                            Back to clusters
                        </Button>
                    ) : (
                        <LemonButton type="secondary" size="small" to={backUrl} data-attr="clusters-back-button">
                            Back to clusters
                        </LemonButton>
                    )
                }
            />
            <div className="@container space-y-4">
                {windowStart && windowEnd && (
                    <div className="text-xs text-muted">
                        <TZLabel time={windowStart} formatDate="MMM D" formatTime="" /> –{' '}
                        <TZLabel time={windowEnd} formatDate="MMM D, YYYY" formatTime="" />
                    </div>
                )}
                <div className="grid grid-cols-1 @[1100px]:grid-cols-[minmax(0,3fr)_minmax(360px,2fr)] gap-4 items-start">
                    <div className="min-w-0 space-y-4">
                        <ClusterDetailMetrics />
                        <LemonCard hoverEffect={false} className="p-4">
                            <h3 className="text-sm font-semibold mb-2">About this cluster</h3>
                            <ClusterDescription description={cluster.description} />
                        </LemonCard>
                        <LemonCard hoverEffect={false} className="p-0 overflow-hidden">
                            <div className="p-3 border-b space-y-3">
                                <div className="flex items-center justify-between gap-2">
                                    <h3 className="text-sm font-semibold mb-0">
                                        {itemLabel}{' '}
                                        <span className="text-muted font-normal">
                                            ({totalTraces}
                                            {totalTraces !== unfilteredTotalTraces
                                                ? ` of ${unfilteredTotalTraces}`
                                                : ''}
                                            )
                                        </span>
                                    </h3>
                                    {filteredItemIdsLoading && <Spinner className="text-sm" />}
                                </div>
                                {clusteringLevel !== 'evaluation' && (
                                    <div className="flex items-center flex-wrap gap-2">
                                        <PropertyFilters
                                            buttonText={`Filter ${itemLabel.toLowerCase()}`}
                                            propertyFilters={propertyFilters}
                                            taxonomicGroupTypes={[
                                                TaxonomicFilterGroupType.EventProperties,
                                                TaxonomicFilterGroupType.PersonProperties,
                                                ...groupsTaxonomicTypes,
                                                TaxonomicFilterGroupType.Cohorts,
                                                TaxonomicFilterGroupType.HogQLExpression,
                                            ]}
                                            onChange={setPropertyFilters}
                                            pageKey="llm-analytics-cluster-detail"
                                        />
                                        <Tooltip title="Filter the items shown in this cluster by their properties. This does not change how clusters are created or affect future runs.">
                                            <IconQuestion className="text-muted" />
                                        </Tooltip>
                                        <div className="flex-1" />
                                        <TestAccountFilterSwitch
                                            checked={shouldFilterTestAccounts}
                                            onChange={setShouldFilterTestAccounts}
                                        />
                                    </div>
                                )}
                            </div>
                            <ClusterItemsTable
                                rows={paginatedTracesWithSummaries}
                                clusteringLevel={clusteringLevel}
                                itemMetrics={itemMetrics}
                                loading={
                                    traceSummariesLoading && !paginatedTracesWithSummaries.some((row) => row.summary)
                                }
                                listId="cluster-traces"
                            />
                            {totalPages > 1 && (
                                <div className="flex items-center justify-between border-t p-3">
                                    <span className="text-xs text-muted">
                                        Page {currentPage} of {totalPages}
                                    </span>
                                    <div className="flex gap-2">
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            icon={<IconChevronLeft />}
                                            disabledReason={currentPage === 1 ? 'First page' : undefined}
                                            onClick={() => setPage(currentPage - 1)}
                                            data-attr="clusters-previous-page"
                                        >
                                            Previous
                                        </LemonButton>
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            icon={<IconChevronRight />}
                                            disabledReason={currentPage === totalPages ? 'Last page' : undefined}
                                            onClick={() => setPage(currentPage + 1)}
                                            data-attr="clusters-next-page"
                                        >
                                            Next
                                        </LemonButton>
                                    </div>
                                </div>
                            )}
                        </LemonCard>
                    </div>
                    <LemonCard hoverEffect={false} className="min-w-0 p-3 sticky top-4">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="text-sm font-semibold mb-0">Cluster map</h3>
                            <span className="text-xs text-muted">
                                {totalTraces} {itemLabel.toLowerCase()}
                            </span>
                        </div>
                        <ClusterDetailScatterPlot />
                        <div className="text-xs text-muted mt-3">Drag to zoom · Double-click to reset</div>
                    </LemonCard>
                </div>
            </div>
            <TraceDrawerRowsSync listId="cluster-traces" rows={drawerRows} />
            <TraceDrawerHost listId="cluster-traces" />
        </SceneContent>
    )
}
