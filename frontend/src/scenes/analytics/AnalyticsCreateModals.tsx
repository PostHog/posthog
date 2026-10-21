import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'

import { NewInsightDialog } from './NewInsightDialog'

/**
 * The create dialogs an Analytics page hosts, so "New dashboard" and "New insight" open in place.
 * `newAnalyticsLogic` falls back to the products' own pages when no host is mounted.
 */
export function AnalyticsCreateModals(): JSX.Element {
    return (
        <>
            <NewDashboardModal />
            <NewInsightDialog />
        </>
    )
}
