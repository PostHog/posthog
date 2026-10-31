import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { billingLogic } from './billingLogic'

export function GrandfatheredEventsRetentionNotice({ className }: { className?: string }): JSX.Element | null {
    const { hasGrandfatheredEventsRetention } = useValues(billingLogic)

    if (!hasGrandfatheredEventsRetention) {
        return null
    }

    return (
        <LemonBanner type="warning" className={className}>
            Your organization keeps 7 years of events data retention from an older plan. This change ends that
            permanently, and your events data retention follows your new plan.
        </LemonBanner>
    )
}
