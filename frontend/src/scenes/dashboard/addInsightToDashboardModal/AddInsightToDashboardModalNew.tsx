import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconCheck, IconFunnels, IconPlus, IconRetention, IconTrends } from '@posthog/icons'

import { InsightPickerTable } from 'lib/components/InsightPicker/InsightPickerTable'
import { insightPickerLogic } from 'lib/components/InsightPicker/insightPickerLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Popover } from 'lib/lemon-ui/Popover'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { DashboardActionButton } from 'scenes/saved-insights/components/DashboardActionButton'
import { insightDashboardModalLogic } from 'scenes/saved-insights/insightDashboardModalLogic'
import { urls } from 'scenes/urls'

import { InsightType, QueryBasedInsightModel } from '~/types'

import { addInsightToDashboardLogic } from '../addInsightToDashboardModalLogic'
import { dashboardLogic } from '../dashboardLogic'

const QUICK_CREATE_TYPES = [
    { type: InsightType.TRENDS, icon: IconTrends, label: 'Trend' },
    { type: InsightType.FUNNELS, icon: IconFunnels, label: 'Funnel' },
    { type: InsightType.RETENTION, icon: IconRetention, label: 'Retention' },
]

export function AddInsightToDashboardModalNew(): JSX.Element {
    const { hideAddInsightToDashboardModal, toggleShowMoreInsightTypes } = useActions(addInsightToDashboardLogic)
    const { addInsightToDashboardModalVisible, showMoreInsightTypes } = useValues(addInsightToDashboardLogic)
    const { dashboard } = useValues(dashboardLogic)

    const handleClose = (): void => {
        posthog.capture('insight dashboard modal - closed')
        hideAddInsightToDashboardModal()
        insightPickerLogic({ logicKey: 'dashboard' }).actions.resetFilters()
    }

    const handleNewInsightClicked = (insightType: string): void => {
        posthog.capture('insight dashboard modal - new insight clicked', {
            insight_type: insightType,
        })
    }
    const { isInsightInDashboard, dashboardUpdatesInProgress } = useValues(insightDashboardModalLogic)
    const { toggleInsightOnDashboard, syncOptimisticStateWithDashboard } = useActions(insightDashboardModalLogic)

    useEffect(() => {
        if (dashboard?.tiles) {
            syncOptimisticStateWithDashboard(dashboard.tiles)
        }
    }, [dashboard?.tiles, syncOptimisticStateWithDashboard])

    const additionalTypes = Object.entries(INSIGHT_TYPES_METADATA).filter(
        ([type, meta]) =>
            meta.inMenu &&
            type !== InsightType.JSON &&
            type !== InsightType.HOG &&
            !QUICK_CREATE_TYPES.some((qt) => qt.type === type)
    )

    const handleRowClick = (insight: QueryBasedInsightModel): void => {
        if (dashboardUpdatesInProgress[insight.id] || !dashboard?.id) {
            return
        }
        const currentlyInDashboard = isInsightInDashboard(insight, dashboard.tiles)
        posthog.capture('insight dashboard modal row clicked', {
            action: currentlyInDashboard ? 'remove' : 'add',
            insight_id: insight.id,
            dashboard_id: dashboard.id,
        })
        toggleInsightOnDashboard(insight, dashboard.id, currentlyInDashboard)
    }

    return (
        <LemonModal
            title="Add insight to dashboard"
            onClose={handleClose}
            isOpen={addInsightToDashboardModalVisible}
            width="min(80vw, 64rem)"
        >
            <div className="space-y-4">
                <div className="flex items-center gap-3 p-4 bg-surface-secondary rounded-lg">
                    <IconPlus className="text-2xl text-secondary shrink-0" />
                    <div className="flex-1">
                        <div className="font-semibold text-base">Create a new insight</div>
                        <div className="text-sm text-secondary">Build a new insight and add it to this dashboard</div>
                    </div>
                    <div className="flex items-center gap-2">
                        {QUICK_CREATE_TYPES.map(({ type, icon: Icon, label }) => (
                            <LemonButton
                                key={type}
                                type="primary"
                                icon={<Icon />}
                                to={urls.insightNew({ type: type, dashboardId: dashboard?.id })}
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
                                        return (
                                            <LemonButton
                                                key={type}
                                                type="tertiary"
                                                fullWidth
                                                icon={Icon ? <Icon /> : undefined}
                                                to={urls.insightNew({
                                                    type: type as InsightType,
                                                    dashboardId: dashboard?.id,
                                                })}
                                                data-attr={`create-${type.toLowerCase()}`}
                                                onClick={() => handleNewInsightClicked(type)}
                                            >
                                                {metadata.name}
                                            </LemonButton>
                                        )
                                    })}
                                </div>
                            }
                        >
                            <LemonButton type="secondary" onClick={() => toggleShowMoreInsightTypes()}>
                                More
                            </LemonButton>
                        </Popover>
                    </div>
                </div>

                <InsightPickerTable
                    logicKey="dashboard"
                    showTagsColumn
                    renderActionColumn={(insight: QueryBasedInsightModel) => (
                        <DashboardActionButton insight={insight} />
                    )}
                    rowClassName={(insight) =>
                        isInsightInDashboard(insight, dashboard?.tiles)
                            ? 'bg-success-highlight border-l-2 border-l-success cursor-pointer hover:bg-success-highlight/70'
                            : 'cursor-pointer hover:bg-success-highlight/30 border-l-2 border-l-transparent hover:border-l-success/50'
                    }
                    onRow={(insight) => ({
                        onClick: () => handleRowClick(insight),
                        title: isInsightInDashboard(insight, dashboard?.tiles)
                            ? 'Click to remove from dashboard'
                            : 'Click to add to dashboard',
                    })}
                    extraColumns={[
                        {
                            key: 'status',
                            width: 32,
                            render: function renderStatus(_: unknown, insight: QueryBasedInsightModel) {
                                return isInsightInDashboard(insight, dashboard?.tiles) ? (
                                    <IconCheck className="text-success text-xl" />
                                ) : null
                            },
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}
