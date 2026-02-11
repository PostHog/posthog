import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'
import posthog from 'posthog-js'

import { IconFunnels, IconPlus, IconRetention, IconTrends } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Popover } from 'lib/lemon-ui/Popover'
import { AddSavedInsightsToDashboard } from 'scenes/saved-insights/AddSavedInsightsToDashboard'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

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
    }

    const handleNewInsightClicked = (insightType: string): void => {
        posthog.capture('insight dashboard modal - new insight clicked', {
            insight_type: insightType,
        })
    }

    const additionalTypes = Object.entries(INSIGHT_TYPES_METADATA).filter(
        ([type, meta]) =>
            meta.inMenu &&
            type !== InsightType.JSON &&
            type !== InsightType.HOG &&
            !QUICK_CREATE_TYPES.some((qt) => qt.type === type)
    )

    return (
        <BindLogic logic={addSavedInsightsModalLogic} props={{}}>
            <LemonModal
                title="Add insight to dashboard"
                onClose={handleClose}
                isOpen={addInsightToDashboardModalVisible}
                width={860}
            >
                <div className="bg-surface-secondary rounded-lg p-4 space-y-3">
                    <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                        <div className="flex items-center gap-3">
                            <IconPlus className="text-2xl text-secondary shrink-0" />
                            <div>
                                <div className="font-semibold text-base">Create a new insight</div>
                                <div className="text-sm text-secondary">
                                    Build a new insight and add it to this dashboard
                                </div>
                            </div>
                        </div>
                        <div className="flex items-center gap-2 sm:ml-auto flex-wrap">
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

                    <LemonDivider />

                    <AddSavedInsightsToDashboard />
                </div>
            </LemonModal>
        </BindLogic>
    )
}
