import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { AddSavedInsightsToDashboard } from 'scenes/saved-insights/AddSavedInsightsToDashboard'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { AddInsightToDashboardModalNew } from './addInsightToDashboardModal/AddInsightToDashboardModalNew'
import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { dashboardLogic } from './dashboardLogic'

export function AddInsightToDashboardModal(): JSX.Element {
    const isExperimentEnabled = useFeatureFlag('PRODUCT_ANALYTICS_ADD_INSIGHT_TO_DASHBOARD_MODAL', 'test')
    const { hideAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { addInsightToDashboardModalVisible } = useValues(addInsightToDashboardLogic)
    const { dashboard } = useValues(dashboardLogic)

    if (isExperimentEnabled) {
        return <AddInsightToDashboardModalNew />
    }

    return (
        <BindLogic logic={addSavedInsightsModalLogic} props={{}}>
            <LemonModal
                title="Add insight to dashboard"
                onClose={hideAddInsightToDashboardModal}
                isOpen={addInsightToDashboardModalVisible}
                footer={
                    <>
                        <LemonButton
                            type="secondary"
                            data-attr="dashboard-cancel"
                            onClick={hideAddInsightToDashboardModal}
                        >
                            Cancel
                        </LemonButton>
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Insight}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                data-attr="dashboard-add-new-insight"
                                to={urls.insightNew({ dashboardId: dashboard?.id })}
                            >
                                New insight
                            </LemonButton>
                        </AccessControlAction>
                    </>
                }
            >
                <AddSavedInsightsToDashboard />
            </LemonModal>
        </BindLogic>
    )
}
