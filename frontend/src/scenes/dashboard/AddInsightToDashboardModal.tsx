import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { addInsightToDashboardLogic } from 'scenes/dashboard/addInsightToDasboardModalLogic'
import { AddSavedInsightsToDashboard } from 'scenes/saved-insights/AddSavedInsightsToDashboard'
import { urls } from 'scenes/urls'

import { dashboardLogic } from './dashboardLogic'

export function AddInsightToDashboardModal(): JSX.Element {
    const { hideAddInsightToDashboardModal } = useActions(addInsightToDashboardLogic)
    const { addInsightToDashboardModalVisible } = useValues(addInsightToDashboardLogic)
    const { dashboard } = useValues(dashboardLogic)
    return (
        <LemonModal
            title="Add insight to dashboard"
            onClose={hideAddInsightToDashboardModal}
            isOpen={addInsightToDashboardModalVisible}
            footer={
                <>
                    <LemonButton type="secondary" data-attr="dashboard-cancel" onClick={hideAddInsightToDashboardModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="dashboard-add-new-insight"
                        to={urls.insightNew(undefined, dashboard?.id)}
                    >
                        New insight
                    </LemonButton>
                </>
            }
        >
            {/* <p>Add insight to dashboard {dashboard?.name}</p> */}
            <AddSavedInsightsToDashboard />
        </LemonModal>
    )
}
