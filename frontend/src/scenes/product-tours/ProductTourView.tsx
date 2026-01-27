import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { SurveyMatchTypeLabels } from 'scenes/surveys/constants'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Query } from '~/queries/Query/Query'
import { DateRange, FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import {
    ActivityScope,
    FeatureFlagFilters,
    FunnelConversionWindowTimeUnit,
    FunnelVizType,
    ProductTour,
    ProductTourStep,
    ProgressStatus,
    PropertyFilterType,
    PropertyOperator,
    StepOrderValue,
    StepOrderVersion,
    SurveyMatchType,
} from '~/types'

import { ProductTourStatsSummary } from './components/ProductTourStatsSummary'
import { ProductToursToolbarButton } from './components/ProductToursToolbarButton'
import { productTourLogic } from './productTourLogic'
import { getProductTourStatus, isAnnouncement, isProductTourRunning, productToursLogic } from './productToursLogic'

export function ProductTourView({ id }: { id: string }): JSX.Element {
    const { productTour, productTourLoading, tourStats, tourStatsLoading, dateRange, targetingFlagFilters } = useValues(
        productTourLogic({ id })
    )
    const { editingProductTour, launchProductTour, stopProductTour, resumeProductTour, setDateRange } = useActions(
        productTourLogic({ id })
    )
    const { deleteProductTour } = useActions(productToursLogic)

    const [tabKey, setTabKey] = useState('overview')

    if (productTourLoading || !productTour) {
        return <LemonSkeleton />
    }

    const status = getProductTourStatus(productTour)
    const isRunning = isProductTourRunning(productTour)

    return (
        <SceneContent>
            <ScenePanel>
                <ScenePanelInfoSection>
                    <SceneFile dataAttrKey="product_tour" />
                </ScenePanelInfoSection>
                <ScenePanelDivider />
                <ScenePanelActionsSection>
                    <ButtonPrimitive
                        menuItem
                        variant="danger"
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Delete this product tour?',
                                content: (
                                    <div className="text-sm text-secondary">
                                        This action cannot be undone. All tour data will be permanently removed.
                                    </div>
                                ),
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    onClick: () => deleteProductTour(id),
                                    size: 'small',
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                    type: 'tertiary',
                                    size: 'small',
                                },
                            })
                        }}
                    >
                        <IconTrash />
                        Delete product tour
                    </ButtonPrimitive>
                </ScenePanelActionsSection>
            </ScenePanel>

            <SceneTitleSection
                name={productTour.name}
                description={productTour.description}
                resourceType={{ type: 'product_tour' }}
                isLoading={productTourLoading}
                actions={
                    <>
                        <ProductToursToolbarButton
                            tourId={id}
                            mode={isAnnouncement(productTour) ? 'preview' : 'edit'}
                        />
                        <LemonButton type="secondary" size="small" onClick={() => editingProductTour(true)}>
                            Edit
                        </LemonButton>
                        {status === ProgressStatus.Draft && (
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Launch this product tour?',
                                        content: (
                                            <div className="text-sm text-secondary">
                                                The tour will immediately start displaying to users matching the display
                                                conditions.
                                            </div>
                                        ),
                                        primaryButton: {
                                            children: 'Launch',
                                            type: 'primary',
                                            onClick: launchProductTour,
                                            size: 'small',
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                            type: 'tertiary',
                                            size: 'small',
                                        },
                                    })
                                }}
                            >
                                Launch
                            </LemonButton>
                        )}
                        {isRunning && (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                size="small"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Stop this product tour?',
                                        content: (
                                            <div className="text-sm text-secondary">
                                                The tour will no longer be displayed to users.
                                            </div>
                                        ),
                                        primaryButton: {
                                            children: 'Stop',
                                            type: 'primary',
                                            onClick: stopProductTour,
                                            size: 'small',
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                            type: 'tertiary',
                                            size: 'small',
                                        },
                                    })
                                }}
                            >
                                Stop
                            </LemonButton>
                        )}
                        {status === ProgressStatus.Complete && !productTour.archived && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Resume this product tour?',
                                        content: (
                                            <div className="text-sm text-secondary">
                                                Once resumed, the tour will be visible to your users again.
                                            </div>
                                        ),
                                        primaryButton: {
                                            children: 'Resume',
                                            type: 'primary',
                                            onClick: resumeProductTour,
                                            size: 'small',
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                            type: 'tertiary',
                                            size: 'small',
                                        },
                                    })
                                }}
                            >
                                Resume
                            </LemonButton>
                        )}
                    </>
                }
            />

            <LemonTabs
                activeKey={tabKey}
                onChange={setTabKey}
                sceneInset
                tabs={[
                    {
                        key: 'overview',
                        label: 'Overview',
                        content: (
                            <div className="space-y-4">
                                <ProductTourStatsSummary
                                    stats={tourStats}
                                    loading={tourStatsLoading}
                                    headerAction={
                                        <DateFilter
                                            dateFrom={dateRange.date_from}
                                            dateTo={dateRange.date_to}
                                            onChange={(dateFrom, dateTo) =>
                                                setDateRange({ date_from: dateFrom, date_to: dateTo })
                                            }
                                        />
                                    }
                                />
                                <LemonDivider />
                                {!isAnnouncement(productTour) && (
                                    <>
                                        <StepsFunnel tour={productTour} dateRange={dateRange} />
                                        <LemonDivider />
                                    </>
                                )}
                                <TargetingSummary tour={productTour} targetingFlagFilters={targetingFlagFilters} />
                            </div>
                        ),
                    },
                    {
                        key: 'history',
                        label: 'History',
                        content: <ActivityLog scope={ActivityScope.PRODUCT_TOUR} id={id} />,
                    },
                ]}
            />
        </SceneContent>
    )
}

/** Get the steps snapshot from a specific version */
function getStepsForVersion(allSteps: ProductTourStep[], version: StepOrderVersion | null): ProductTourStep[] {
    if (!version) {
        return allSteps
    }
    return version.steps
}

/** Format version date for display */
function formatVersionDate(dateString: string): string {
    const date = new Date(dateString)
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function StepsFunnel({ tour, dateRange }: { tour: ProductTour; dateRange: DateRange }): JSX.Element {
    const allSteps = tour.content?.steps || []
    const stepOrderHistory = tour.content?.step_order_history || []
    const hasVersionHistory = stepOrderHistory.length > 1

    // Default to latest version (last in array)
    const [selectedVersionId, setSelectedVersionId] = useState<string | null>(
        stepOrderHistory.length > 0 ? stepOrderHistory[stepOrderHistory.length - 1].id : null
    )

    if (allSteps.length === 0) {
        return <div className="text-secondary text-sm">No steps defined for this tour.</div>
    }

    // Find the selected version and determine its date range
    const selectedVersionIndex = stepOrderHistory.findIndex((v) => v.id === selectedVersionId)
    const selectedVersion = selectedVersionIndex >= 0 ? stepOrderHistory[selectedVersionIndex] : null
    const nextVersion = selectedVersionIndex >= 0 ? stepOrderHistory[selectedVersionIndex + 1] : null

    // Get steps in the order of the selected version
    const steps = getStepsForVersion(allSteps, selectedVersion)

    // Calculate date range for this version
    // Start: version's created_at (or tour start_date, or user-selected date_from)
    // End: next version's created_at (or user-selected date_to)
    const versionDateFrom = selectedVersion?.created_at || dateRange.date_from
    const versionDateTo = nextVersion?.created_at || dateRange.date_to

    const tourIdFilter = {
        type: PropertyFilterType.Event,
        key: '$product_tour_id',
        operator: PropertyOperator.Exact,
        value: tour.id,
    }

    // Build funnel: tour shown → step 1 shown → step 2 shown → ... → tour completed
    // Filter by step ID (stable across reorders) rather than step order (positional)
    const series = [
        {
            kind: NodeKind.EventsNode,
            event: 'product tour shown',
            custom_name: 'Tour started',
            properties: [tourIdFilter],
        },
        ...steps.map((step, index) => ({
            kind: NodeKind.EventsNode,
            event: 'product tour step shown',
            custom_name: `Step ${index + 1}`,
            properties: [
                tourIdFilter,
                {
                    type: PropertyFilterType.Event,
                    key: '$product_tour_step_id',
                    operator: PropertyOperator.Exact,
                    value: step.id,
                },
            ],
        })),
        {
            kind: NodeKind.EventsNode,
            event: 'product tour completed',
            custom_name: 'Completed',
            properties: [tourIdFilter],
        },
    ]

    const funnelsQuery: FunnelsQuery = {
        kind: NodeKind.FunnelsQuery,
        series: series as FunnelsQuery['series'],
        funnelsFilter: {
            funnelVizType: FunnelVizType.Steps,
            funnelOrderType: StepOrderValue.ORDERED,
            funnelWindowInterval: 14,
            funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit.Day,
        },
        dateRange: {
            date_from: versionDateFrom,
            date_to: versionDateTo,
        },
    }

    // Build version options for dropdown
    const versionOptions = stepOrderHistory.map((version, index) => ({
        value: version.id,
        label: `Version ${index + 1} (${formatVersionDate(version.created_at)})`,
    }))

    return (
        <div>
            <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold">Step completion funnel</h3>
                {hasVersionHistory && (
                    <LemonSelect
                        size="small"
                        options={versionOptions}
                        value={selectedVersionId}
                        onChange={(value) => setSelectedVersionId(value)}
                    />
                )}
            </div>
            {hasVersionHistory && selectedVersion && (
                <div className="text-secondary text-sm mb-4">
                    Showing data from {formatVersionDate(selectedVersion.created_at)}
                    {nextVersion ? ` to ${formatVersionDate(nextVersion.created_at)}` : ' to now'}
                </div>
            )}
            <Query
                query={{
                    kind: NodeKind.InsightVizNode,
                    source: funnelsQuery,
                    showTable: false,
                    showLastComputation: true,
                    showLastComputationRefresh: false,
                }}
                readOnly
            />
        </div>
    )
}

function TargetingSummary({
    tour,
    targetingFlagFilters,
}: {
    tour: ProductTour
    targetingFlagFilters?: FeatureFlagFilters
}): JSX.Element {
    const conditions = tour.content?.conditions || {}
    const hasUrl = conditions.url
    const hasTargetingFilters =
        targetingFlagFilters && targetingFlagFilters.groups && targetingFlagFilters.groups.length > 0
    const hasConditions = hasUrl || hasTargetingFilters

    return (
        <div className="flex flex-col gap-2">
            <h3 className="font-semibold">Display conditions</h3>
            <span className="text-secondary">
                {hasConditions
                    ? 'Tour will be displayed to users that match the following conditions:'
                    : 'Tour will be displayed to all users.'}
            </span>
            {hasUrl && (
                <div className="flex flex-col font-medium gap-1">
                    <div className="flex flex-row gap-1">
                        <span>URL {SurveyMatchTypeLabels[conditions.urlMatchType || SurveyMatchType.Contains]}:</span>
                        <LemonTag>{conditions.url}</LemonTag>
                    </div>
                </div>
            )}
            {hasTargetingFilters && (
                <div>
                    <BindLogic logic={featureFlagLogic} props={{ id: tour.internal_targeting_flag?.id || 'new' }}>
                        <span className="font-medium">Person properties:</span>
                        <FeatureFlagReleaseConditions readOnly excludeTitle filters={targetingFlagFilters} />
                    </BindLogic>
                </div>
            )}
        </div>
    )
}
