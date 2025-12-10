import { BindLogic, useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

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
    FeatureFlagFilters,
    FunnelConversionWindowTimeUnit,
    FunnelVizType,
    ProductTour,
    ProgressStatus,
    PropertyFilterType,
    PropertyOperator,
    StepOrderValue,
} from '~/types'

import { EditInToolbarButton } from './components/EditInToolbarButton'
import { ProductTourStatsSummary } from './components/ProductTourStatsSummary'
import { productTourLogic } from './productTourLogic'
import { getProductTourStatus, isProductTourRunning, productToursLogic } from './productToursLogic'

const UrlMatchTypeLabels: Record<string, string> = {
    contains: 'contains',
    exact: 'exactly matches',
    regex: 'matches regex',
}

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
                        <EditInToolbarButton tourId={id} />
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
                                <StepsFunnel tour={productTour} dateRange={dateRange} />
                                <LemonDivider />
                                <TargetingSummary tour={productTour} targetingFlagFilters={targetingFlagFilters} />
                            </div>
                        ),
                    },
                ]}
            />
        </SceneContent>
    )
}

function StepsFunnel({ tour, dateRange }: { tour: ProductTour; dateRange: DateRange }): JSX.Element {
    const steps = tour.content?.steps || []

    if (steps.length === 0) {
        return <div className="text-secondary text-sm">No steps defined for this tour.</div>
    }

    const tourIdFilter = {
        type: PropertyFilterType.Event,
        key: '$product_tour_id',
        operator: PropertyOperator.Exact,
        value: tour.id,
    }

    // Build funnel: tour shown → step 0 shown → step 1 shown → ... → tour completed
    const series = [
        {
            kind: NodeKind.EventsNode,
            event: 'product tour shown',
            custom_name: 'Tour started',
            properties: [tourIdFilter],
        },
        ...steps.map((_, index) => ({
            kind: NodeKind.EventsNode,
            event: 'product tour step shown',
            custom_name: `Step ${index + 1}`,
            properties: [
                tourIdFilter,
                {
                    type: PropertyFilterType.Event,
                    key: '$product_tour_step_order',
                    operator: PropertyOperator.Exact,
                    value: String(index),
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
            date_from: dateRange.date_from,
            date_to: dateRange.date_to,
        },
    }

    return (
        <div>
            <h3 className="font-semibold mb-4">Step completion funnel</h3>
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
                    <div className="flex-row">
                        <span>URL {UrlMatchTypeLabels[conditions.urlMatchType || 'contains']}:</span>{' '}
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
