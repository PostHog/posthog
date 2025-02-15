import { useActions, useValues } from 'kea'
import { BindLogic } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { addSavedInsightsModalLogic } from 'scenes/saved-insights/addSavedInsightsModalLogic'
import { AddSavedInsightsToDashboard } from 'scenes/saved-insights/AddSavedInsightsToDashboard'
import { urls } from 'scenes/urls'

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
                        <LemonButton
                            type="primary"
                            data-attr="dashboard-add-new-insight"
                            to={urls.insightNew({ dashboardId: dashboard?.id })}
                        >
                            New insight
                        </LemonButton>
                    </>
                }
            >
                <AddSavedInsightsToDashboard />
            </LemonModal>
        </BindLogic>
    )
}
