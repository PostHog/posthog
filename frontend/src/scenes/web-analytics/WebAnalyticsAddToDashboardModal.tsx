import { useActions, useValues } from 'kea'

import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'

import { webAnalyticsAddToDashboardLogic } from './webAnalyticsAddToDashboardLogic'

export const WebAnalyticsAddToDashboardModal = (): JSX.Element | null => {
    const { savedInsight, isAddToDashboardModalOpen } = useValues(webAnalyticsAddToDashboardLogic)
    const { closeAddToDashboardModal } = useActions(webAnalyticsAddToDashboardLogic)

    if (!savedInsight) {
        return null
    }

    return (
        <>
            <AddToDashboardModal
                isOpen={isAddToDashboardModalOpen}
                closeModal={closeAddToDashboardModal}
                insightProps={{ dashboardItemId: savedInsight.short_id, cachedInsight: savedInsight }}
                canEditInsight
                data-attr="web-analytics-add-to-dashboard-modal"
            />
            {/* The picker's "Add to a new dashboard" only opens this dialog, so the two have to be
                rendered together (as the insight scene does). */}
            <NewDashboardModal />
        </>
    )
}
