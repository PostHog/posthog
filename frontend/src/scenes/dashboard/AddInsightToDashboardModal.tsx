import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { AddSavedInsightsToDashboard } from 'scenes/saved-insights/AddSavedInsightsToDashboard'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { addInsightToDashboardLogic } from './addInsightToDashboardModalLogic'
import { dashboardLogic } from './dashboardLogic'

export function AddInsightToDashboardModal(): JSX.Element {
    const { hideAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { addInsightToDashboardModalVisible } = useValues(addInsightToDashboardLogic)
    const { dashboard } = useValues(dashboardLogic)
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
