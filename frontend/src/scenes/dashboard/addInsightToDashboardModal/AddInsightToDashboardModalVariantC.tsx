import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { IconFunnels, IconPlus, IconRetention, IconTrends, IconUserPaths } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Popover } from 'lib/lemon-ui/Popover'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

import { addInsightToDashboardLogic } from '../addInsightToDashboardModalLogic'
import { dashboardLogic } from '../dashboardLogic'
import { StreamlinedInsightsTable } from './StreamlinedInsightsTable'

const QUICK_CREATE_TYPES = [
    { type: InsightType.TRENDS, icon: IconTrends, label: 'Trend' },
    { type: InsightType.FUNNELS, icon: IconFunnels, label: 'Funnel' },
    { type: InsightType.RETENTION, icon: IconRetention, label: 'Retention' },
    { type: InsightType.PATHS, icon: IconUserPaths, label: 'Path' },
]

export function AddInsightToDashboardModalVariantC(): JSX.Element {
    const { hideAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { addInsightToDashboardModalVisible } = useValues(addInsightToDashboardLogic)
    const { dashboard } = useValues(dashboardLogic)
    const [showMoreTypes, setShowMoreTypes] = useState(false)

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
                onClose={hideAddInsightToDashboardModal}
                isOpen={addInsightToDashboardModalVisible}
                width={860}
            >
                <div className="space-y-4">
                    {/* Create new section */}
                    <LemonCard className="bg-surface-tertiary border-dashed">
                        <div className="flex items-center justify-between gap-4 p-1">
                            <div className="flex items-center gap-3">
                                <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-surface-primary">
                                    <IconPlus className="text-xl text-secondary" />
                                </div>
                                <div>
                                    <div className="font-semibold">Create new insight</div>
                                    <div className="text-xs text-secondary">
                                        Build a new insight and add it to this dashboard
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                {QUICK_CREATE_TYPES.map(({ type, icon: Icon, label }) => (
                                    <LemonButton
                                        key={type}
                                        type="secondary"
                                        size="small"
                                        icon={<Icon />}
                                        to={urls.insightNew({ type: type, dashboardId: dashboard?.id })}
                                        tooltip={INSIGHT_TYPES_METADATA[type]?.description}
                                        data-attr={`quick-create-${type.toLowerCase()}`}
                                    >
                                        {label}
                                    </LemonButton>
                                ))}
                                <Popover
                                    visible={showMoreTypes}
                                    onClickOutside={() => setShowMoreTypes(false)}
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
                                                    >
                                                        {metadata.name}
                                                    </LemonButton>
                                                )
                                            })}
                                        </div>
                                    }
                                >
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => setShowMoreTypes(!showMoreTypes)}
                                    >
                                        More
                                    </LemonButton>
                                </Popover>
                            </div>
                        </div>
                    </LemonCard>

                    {/* Existing insights section */}
                    <div>
                        <h4 className="font-semibold mb-3">Or add an existing insight</h4>
                        <StreamlinedInsightsTable dashboardId={dashboard?.id} />
                    </div>
                </div>
            </LemonModal>
        </BindLogic>
    )
}
