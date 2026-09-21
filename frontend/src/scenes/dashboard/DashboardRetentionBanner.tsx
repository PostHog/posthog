import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { dataRetentionBannerLogic } from '../insights/dataRetention/dataRetentionBannerLogic'
import { dashboardLogic } from './dashboardLogic'

export const DashboardRetentionBanner = (): JSX.Element | null => {
    const { showRetentionBanner, retentionPeriodLabel } = useValues(dashboardLogic)
    const { snooze } = useActions(dataRetentionBannerLogic)

    if (!showRetentionBanner || !retentionPeriodLabel) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            className="mt-4 mb-2"
            onClose={snooze}
            action={{ children: 'Upgrade plan', to: urls.organizationBilling() }}
        >
            Some insights on this dashboard have date ranges that go beyond your {retentionPeriodLabel} data retention,
            so events older than that aren't included.
        </LemonBanner>
    )
}
