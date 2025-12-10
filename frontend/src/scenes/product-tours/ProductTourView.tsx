import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonDivider, LemonTag } from '@posthog/lemon-ui'

import { SceneFile } from 'lib/components/Scenes/SceneFile'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'

import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductTour, ProgressStatus } from '~/types'

import { ProductTourStatsSummary } from './components/ProductTourStatsSummary'
import { ProductTourStats, productTourLogic } from './productTourLogic'
import { getProductTourStatus, isProductTourRunning } from './productToursLogic'
import { productToursLogic } from './productToursLogic'

const UrlMatchTypeLabels: Record<string, string> = {
    contains: 'contains',
    exact: 'exactly matches',
    regex: 'matches regex',
}

export function ProductTourView({ id }: { id: string }): JSX.Element {
    const { productTour, productTourLoading, tourStats, tourStatsLoading } = useValues(productTourLogic({ id }))
    const { editingProductTour, launchProductTour, stopProductTour, resumeProductTour } = useActions(
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
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={`${urls.toolbarLaunch()}?__posthog_product_tour=${id}`}
                            targetBlank
                        >
                            Edit in toolbar
                        </LemonButton>
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
                                <ProductTourStatsSummary stats={tourStats} loading={tourStatsLoading} />
                                <LemonDivider />
                                <StepsFunnel stats={tourStats} tour={productTour} loading={tourStatsLoading} />
                                <LemonDivider />
                                <TargetingSummary tour={productTour} />
                            </div>
                        ),
                    },
                ]}
            />
        </SceneContent>
    )
}

function StepsFunnel({
    stats,
    tour,
    loading,
}: {
    stats: ProductTourStats | null
    tour: ProductTour
    loading: boolean
}): JSX.Element {
    if (loading) {
        return <LemonSkeleton className="h-32" />
    }

    const steps = tour.content?.steps || []
    const stepStats = stats?.stepStats || []

    if (steps.length === 0) {
        return <div className="text-secondary text-sm">No steps defined for this tour.</div>
    }

    return (
        <div>
            <h3 className="font-semibold mb-4">Step completion funnel</h3>
            <div className="space-y-2">
                {steps.map((step, index) => {
                    const stepStat = stepStats.find((s) => s.stepOrder === index)
                    const shown = stepStat?.shown ?? 0
                    const completed = stepStat?.completed ?? 0
                    const completionRate = shown > 0 ? Math.round((completed / shown) * 100) : 0

                    return (
                        <div key={index} className="flex items-center gap-4 p-3 border rounded">
                            <div className="w-8 h-8 rounded-full bg-primary text-white flex items-center justify-center font-semibold">
                                {index + 1}
                            </div>
                            <div className="flex-1">
                                <div className="font-medium">Step {index + 1}</div>
                                <div className="text-secondary text-sm truncate">{step.selector}</div>
                            </div>
                            <div className="text-right">
                                <div className="font-medium">{completionRate}%</div>
                                <div className="text-secondary text-sm">
                                    {completed} / {shown}
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function TargetingSummary({ tour }: { tour: ProductTour }): JSX.Element {
    const conditions = tour.content?.conditions || {}
    const hasUrl = conditions.url
    const hasTargetingFilters =
        tour.targeting_flag_filters &&
        tour.targeting_flag_filters.groups &&
        tour.targeting_flag_filters.groups.length > 0

    return (
        <div>
            <h3 className="font-semibold mb-4">Display conditions</h3>
            <div className="space-y-3">
                {hasUrl && (
                    <div className="flex items-center gap-2">
                        <span className="text-secondary">
                            URL {UrlMatchTypeLabels[conditions.urlMatchType || 'contains']}:
                        </span>
                        <LemonTag>{conditions.url}</LemonTag>
                    </div>
                )}
                {hasTargetingFilters && (
                    <div className="flex items-center gap-2">
                        <span className="text-secondary">Person properties:</span>
                        <span className="text-sm">
                            {tour.targeting_flag_filters!.groups!.length} condition group(s)
                        </span>
                    </div>
                )}
                {tour.internal_targeting_flag && (
                    <div className="flex items-center gap-2">
                        <span className="text-secondary">Feature flag:</span>
                        <LemonTag>{tour.feature_flag_key}</LemonTag>
                    </div>
                )}
                {!hasUrl && !hasTargetingFilters && !tour.internal_targeting_flag && (
                    <span className="text-secondary text-sm">
                        No targeting conditions configured. Tour will display to all users.
                    </span>
                )}
            </div>
        </div>
    )
}
