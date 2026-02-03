import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { INSIGHT_TYPES_METADATA } from 'scenes/saved-insights/SavedInsights'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

import { addInsightToDashboardLogic } from '../addInsightToDashboardModalLogic'
import { dashboardLogic } from '../dashboardLogic'
import { InsightTypeCard } from './InsightTypeCard'
import { StreamlinedInsightsTable } from './StreamlinedInsightsTable'

type TabKey = 'create' | 'existing'

export function AddInsightToDashboardModalVariantB(): JSX.Element {
    const { hideAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { addInsightToDashboardModalVisible } = useValues(addInsightToDashboardLogic)
    const { dashboard } = useValues(dashboardLogic)
    const [activeTab, setActiveTab] = useState<TabKey>('existing')

    const insightTypesForMenu = Object.entries(INSIGHT_TYPES_METADATA).filter(
        ([type, meta]) => meta.inMenu && type !== InsightType.JSON && type !== InsightType.HOG
    )

    return (
        <BindLogic logic={addSavedInsightsModalLogic} props={{}}>
            <LemonModal
                title="Add insight to dashboard"
                onClose={hideAddInsightToDashboardModal}
                isOpen={addInsightToDashboardModalVisible}
                width={860}
            >
                <LemonTabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    tabs={[
                        {
                            key: 'existing' as const,
                            label: 'Add existing',
                            content: <StreamlinedInsightsTable dashboardId={dashboard?.id} />,
                        },
                        {
                            key: 'create' as const,
                            label: 'Create new',
                            content: (
                                <div className="pt-2">
                                    <p className="text-secondary text-sm mb-4">
                                        Create a new insight and add it to this dashboard
                                    </p>
                                    <div className="grid grid-cols-2 gap-3">
                                        {insightTypesForMenu.map(([type, metadata]) => (
                                            <InsightTypeCard
                                                key={type}
                                                type={type}
                                                metadata={metadata}
                                                to={urls.insightNew({
                                                    type: type as InsightType,
                                                    dashboardId: dashboard?.id,
                                                })}
                                            />
                                        ))}
                                    </div>
                                    <div className="mt-4 pt-4 border-t">
                                        <LemonButton
                                            type="secondary"
                                            fullWidth
                                            center
                                            to={urls.insightNew({ dashboardId: dashboard?.id })}
                                            data-attr="create-insight-advanced"
                                        >
                                            Start from scratch
                                        </LemonButton>
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </LemonModal>
        </BindLogic>
    )
}
