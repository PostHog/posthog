import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'
import posthog from 'posthog-js'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Popover } from 'lib/lemon-ui/Popover'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'

import { AddSavedInsightsToDashboard } from 'products/product_analytics/frontend/insights/savedInsights/AddSavedInsightsToDashboard'

import { addInsightToDashboardLogic } from '../../addInsightToDashboardModalLogic'
import { addInsightToDashboardCreateOptions } from './addInsightToDashboardCreateOptions'
import { QuillAddInsightToDashboardModal } from './QuillAddInsightToDashboardModal'

export function AddInsightToDashboardModal(): JSX.Element {
    const { hideAddInsightToDashboardModal, toggleShowMoreInsightTypes } = useActions(addInsightToDashboardLogic)
    const { addInsightToDashboardModalVisible, showMoreInsightTypes } = useValues(addInsightToDashboardLogic)
    const { dashboard, newTileGroupKey } = useValues(dashboardLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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

    const { quickCreate, moreCreate } = addInsightToDashboardCreateOptions({
        dashboardId: dashboard?.id,
        tileGroupKey: newTileGroupKey,
        featureFlags,
    })

    if (todayRailNav) {
        return (
            <BindLogic logic={addSavedInsightsModalLogic} props={{}}>
                <QuillAddInsightToDashboardModal
                    isOpen={addInsightToDashboardModalVisible}
                    onClose={handleClose}
                    onCreateClicked={handleNewInsightClicked}
                    quickCreate={quickCreate}
                    moreCreate={moreCreate}
                />
            </BindLogic>
        )
    }

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
                                {quickCreate.map(({ type, icon: Icon, label, url, dataAttr, tooltip }) => (
                                    <LemonButton
                                        key={type}
                                        type="primary"
                                        size="small"
                                        icon={Icon ? <Icon /> : undefined}
                                        to={url}
                                        tooltip={tooltip}
                                        data-attr={dataAttr}
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
                                            {moreCreate.map(({ type, icon: Icon, label, url, dataAttr }) => (
                                                <LemonButton
                                                    key={type}
                                                    type="tertiary"
                                                    fullWidth
                                                    icon={Icon ? <Icon /> : undefined}
                                                    to={url}
                                                    data-attr={dataAttr}
                                                    onClick={() => handleNewInsightClicked(type)}
                                                >
                                                    {label}
                                                </LemonButton>
                                            ))}
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
