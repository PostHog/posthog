import { useEffect, useState } from 'react'
import { ComponentMeta } from '@storybook/react'
import { BillingType, Realm } from '~/types'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useStorybookMocks } from '~/mocks/browser'
import { BillingAlerts } from './BillingAlerts'
import { useActions } from 'kea'
import { BillingAlertType, billingLogic } from 'scenes/billing/billingLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { LemonSelect } from './LemonSelect'

export default {
    title: 'Components/BillingAlerts',
    component: BillingAlerts,
    parameters: { chromatic: { disableSnapshot: false } },
} as ComponentMeta<typeof BillingAlerts>

const Template = (): JSX.Element => {
    const { loadBillingSuccess } = useActions(billingLogic)
    const [alertType, setAlertType] = useState<BillingAlertType | null>(BillingAlertType.SetupBilling)

    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                realm: Realm.Cloud,
            },
        },
    })

    useEffect(() => {
        router.actions.push(urls.dashboard(2))
        const payload: BillingType = {
            should_setup_billing: false,
            subscription_url: 'https://posthog.com',

            billing_limit_exceeded: false,

            is_billing_active: true,
            current_usage: 0,

            // Misc
            plan: null,
            billing_period_ends: '',
            event_allocation: null,
            current_bill_amount: null,
            current_bill_usage: null,
            should_display_current_bill: true,
            billing_limit: null,
            tiers: null,
            current_bill_cycle: {
                current_period_start: 1,
                current_period_end: 30,
            },
        }

        if (alertType === BillingAlertType.SetupBilling) {
            payload.should_setup_billing = true
            payload.subscription_url = 'https://posthog.com'
        }
        if (alertType === BillingAlertType.UsageLimitExceeded) {
            payload.billing_limit_exceeded = true
        }

        if (alertType === BillingAlertType.UsageNearLimit) {
            payload.current_usage = 99
            payload.event_allocation = 100
        }

        loadBillingSuccess(payload)
    }, [alertType])

    return (
        <div className="space-y-2">
            <BillingAlerts />

            <LemonSelect
                value={alertType ?? undefined}
                onChange={setAlertType}
                options={[
                    { value: BillingAlertType.SetupBilling, label: 'SetupBilling' },
                    { value: BillingAlertType.UsageLimitExceeded, label: 'UsageLimitExceeded' },
                    { value: BillingAlertType.UsageNearLimit, label: 'UsageNearLimit' },
                ]}
            />
        </div>
    )
}

export const _BillingAlerts = (): JSX.Element => {
    return <Template />
}
