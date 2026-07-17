import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { InsightLogicProps } from '~/types'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'
import { insightRetentionBannerLogic } from './insightRetentionBannerLogic'

export function InsightRetentionBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { shouldShowBanner } = useValues(insightRetentionBannerLogic(insightProps))
    const { retentionPeriodLabel } = useValues(dataRetentionBannerLogic)
    const { snooze } = useActions(dataRetentionBannerLogic)

    if (!shouldShowBanner || !retentionPeriodLabel) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            onClose={snooze}
            action={{ children: 'Upgrade to unlock past data', to: urls.organizationBilling() }}
        >
            This insight has the potential to go back further than your {retentionPeriodLabel} of events data retention.
            Older events aren't included in the results.
        </LemonBanner>
    )
}
