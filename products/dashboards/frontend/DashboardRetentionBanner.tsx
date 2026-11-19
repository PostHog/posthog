import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { dataRetentionBannerLogic } from 'products/product_analytics/frontend/insights/dataRetention/dataRetentionBannerLogic'
import { RetentionDeletionMessage } from 'products/product_analytics/frontend/insights/dataRetention/RetentionDeletionMessage'

export const DashboardRetentionBanner = (): JSX.Element | null => {
    const { showRetentionBanner } = useValues(dashboardLogic)
    const { dismiss } = useActions(dataRetentionBannerLogic)

    if (!showRetentionBanner) {
        return null
    }

    return (
        <LemonBanner type="warning" className="mt-4 mb-2" onClose={dismiss}>
            <RetentionDeletionMessage subject="Some insights on this dashboard include events" />
        </LemonBanner>
    )
}
