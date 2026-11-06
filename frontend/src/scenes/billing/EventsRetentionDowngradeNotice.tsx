import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { billingLogic } from 'lib/logic/billing/billingLogic'
import { longestEventsRetentionMonths } from 'lib/logic/billing/eventsRetentionMonths'

import { BillingPlanType } from '~/types'

import { EventsRetentionDowngradeDeletionCount } from 'products/product_analytics/frontend/settings/EventsRetentionDowngradeDeletionCount'
import { retentionPeriodLabel } from 'products/product_analytics/frontend/settings/retentionPeriodLabel'

export function EventsRetentionDowngradeNotice({
    plansAfterChange,
    className,
}: {
    plansAfterChange: (BillingPlanType | null | undefined)[]
    className?: string
}): JSX.Element | null {
    const { hasGrandfatheredEventsRetention, currentEventsRetentionMonths } = useValues(billingLogic)
    const newMonths = longestEventsRetentionMonths(plansAfterChange)

    let message: string
    if (hasGrandfatheredEventsRetention) {
        message =
            'Your organization keeps 7 years of events data retention from an older plan. This change ends that permanently, and your events data retention follows your new plan.'
    } else if (
        newMonths !== null &&
        currentEventsRetentionMonths !== null &&
        newMonths < currentEventsRetentionMonths
    ) {
        message = `This change shortens your events data retention from ${retentionPeriodLabel(currentEventsRetentionMonths)} to ${retentionPeriodLabel(newMonths)}.`
    } else {
        return null
    }

    return (
        <LemonBanner type="warning" className={className}>
            <p className="mb-0">{message}</p>
            {newMonths !== null && <EventsRetentionDowngradeDeletionCount months={newMonths} />}
        </LemonBanner>
    )
}
