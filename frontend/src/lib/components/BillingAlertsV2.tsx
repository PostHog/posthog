import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

export function BillingAlertsV2(): JSX.Element | null {
    const { billingAlert } = useValues(billingLogic)
    const { reportBillingAlertShown } = useActions(billingLogic)
    const { currentLocation } = useValues(router)
    const [alertHidden, setAlertHidden] = useState(false)

    useEffect(() => {
        if (billingAlert) {
            reportBillingAlertShown(billingAlert)
        }
    }, [billingAlert])

    if (!billingAlert || alertHidden) {
        return null
    }

    const showButton = currentLocation.pathname !== urls.organizationBilling()

    const buttonProps = billingAlert.contactSupport
        ? {
              to: 'mailto:sales@posthog.com',
              children: 'Contact support',
          }
        : { to: urls.organizationBilling(), children: 'Manage billing' }

    return (
        <div className="my-4">
            <LemonBanner
                type={billingAlert.status}
                action={showButton ? buttonProps : undefined}
                onClose={billingAlert.status !== 'error' ? () => setAlertHidden(true) : undefined}
            >
                <b>{billingAlert.title}</b>
                <br />
                {billingAlert.message}
            </LemonBanner>
        </div>
    )
}
