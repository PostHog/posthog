import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconInsightFunnels, IconInsightRetention, IconInsightTrends } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Popover } from 'lib/lemon-ui/Popover'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import {
    INSIGHT_TYPES_METADATA,
    QUERY_TYPES_METADATA,
    isInsightTypeCreatable,
} from 'scenes/saved-insights/insightTypesMetadata'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

import { AddSavedInsightsToDashboard } from 'products/product_analytics/frontend/insights/savedInsights/AddSavedInsightsToDashboard'

import { addInsightToDashboardLogic } from '../../addInsightToDashboardModalLogic'

const QUICK_CREATE_TYPES = [
    { type: InsightType.TRENDS, icon: IconInsightTrends, label: 'Trend' },
    { type: InsightType.FUNNELS, icon: IconInsightFunnels, label: 'Funnel' },
    { type: InsightType.RETENTION, icon: IconInsightRetention, label: 'Retention' },
]

export function AddInsightToDashboardModal(): JSX.Element {
    const { hideAddInsightToDashboardModal, toggleShowMoreInsightTypes } = useActions(addInsightToDashboardLogic)
    const { addInsightToDashboardModalVisible, showMoreInsightTypes } = useValues(addInsightToDashboardLogic)
    const { dashboard, newTileGroupKey } = useValues(dashboardLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const handleClose = (): void => {
        posthog.capture('insight dashboard modal - closed')
        hideAddInsightToDashboardModal()
    }

    const handleNewInsightClicked = (insightType: string): void => {
        posthog.capture('insight dashboard modal - new insight clicked', {
            insight_type: insightType,
        })
        handleClose()
    }

    const additionalTypes = Object.entries(INSIGHT_TYPES_METADATA).filter(
        ([type, meta]) =>
            isInsightTypeCreatable(meta, featureFlags) &&
            type !== InsightType.JSON &&
            type !== InsightType.HOG &&
            !QUICK_CREATE_TYPES.some((qt) => qt.type === type)
    )

    const metricsEnabled =
        !!featureFlags[FEATURE_FLAGS.METRICS] && !!featureFlags[FEATURE_FLAGS.METRICS_INSIGHT_BUILDER]
    const MetricsIcon = QUERY_TYPES_METADATA[NodeKind.MetricsQuery].icon

    return (
        <BindLogic logic={addSavedInsightsModalLogic} props={{}}>
            <LemonModal
                title="Add insight to dashboard"
                onClose={handleClose}
                isOpen={addInsightToDashboardModalVisible}
                width={860}
                className="bg-surface-secondary"
            >
                <div className="-mt-1 space-y-3">
                    <LemonBanner type="info" hideIcon className="p-4">
                        <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                            <div className="min-w-0">
                                <div className="font-semibold">Create a new insight</div>
                                <div className="text-xs text-secondary">
                                    Build a new insight and add it to this dashboard
                                </div>
                            </div>
                            <div className="flex items-center gap-2 sm:ml-auto flex-wrap pr-0.5">
                                {QUICK_CREATE_TYPES.map(({ type, icon: Icon, label }) => (
                                    <LemonButton
                                        key={type}
                                        type="primary"
                                        size="small"
                                        icon={<Icon />}
                                        to={urls.insightNew({
                                            type: type,
                                            dashboardId: dashboard?.id,
                                            tileGroupKey: newTileGroupKey,
                                        })}
                                        tooltip={INSIGHT_TYPES_METADATA[type]?.description}
                                        data-attr={`quick-create-${type.toLowerCase()}`}
                                        onClick={() => handleNewInsightClicked(type)}
                                    >
                                        {label}
                                    </LemonButton>
                                ))}
                                <Popover
                                    visible={showMoreInsightTypes}
                                    onClickOutside={() => toggleShowMoreInsightTypes()}
                                    overlay={
                                        <div className="p-2 space-y-1 min-w-48">
                                            {additionalTypes.map(([type, metadata]) => {
                                                const Icon = metadata.icon
                                                const typeUrl =
                                                    type === InsightType.SQL
                                                        ? urls.sqlEditor({
                                                              dashboard: dashboard?.id,
                                                              tileGroupKey: newTileGroupKey,
                                                          })
                                                        : urls.insightNew({
                                                              type: type as InsightType,
                                                              dashboardId: dashboard?.id,
                                                              tileGroupKey: newTileGroupKey,
                                                          })
                                                return (
                                                    <LemonButton
                                                        key={type}
                                                        type="tertiary"
                                                        fullWidth
                                                        icon={Icon ? <Icon /> : undefined}
                                                        to={typeUrl}
                                                        data-attr={`create-${type.toLowerCase()}`}
                                                        onClick={() => handleNewInsightClicked(type)}
                                                    >
                                                        {metadata.name}
                                                    </LemonButton>
                                                )
                                            })}
                                            {metricsEnabled && (
                                                <LemonButton
                                                    type="tertiary"
                                                    fullWidth
                                                    icon={<MetricsIcon />}
                                                    to={urls.insightNew({
                                                        type: InsightType.METRICS,
                                                        dashboardId: dashboard?.id,
                                                        tileGroupKey: newTileGroupKey,
                                                    })}
                                                    data-attr="create-metrics"
                                                    onClick={() => handleNewInsightClicked(InsightType.METRICS)}
                                                >
                                                    {QUERY_TYPES_METADATA[NodeKind.MetricsQuery].name}
                                                </LemonButton>
                                            )}
                                        </div>
                                    }
                                >
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => toggleShowMoreInsightTypes()}
                                    >
                                        More
                                    </LemonButton>
                                </Popover>
                            </div>
                        </div>
                    </LemonBanner>
                    <AddSavedInsightsToDashboard />
                </div>
            </LemonModal>
        </BindLogic>
    )
}
