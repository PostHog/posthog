import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'
import { billingV2Logic } from 'scenes/billing/v2/billingV2Logic'
import { urls } from 'scenes/urls'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'

export function BillingAlertsV2(): JSX.Element | null {
    const { billingAlert, billingVersion } = useValues(billingV2Logic)
    const { reportBillingAlertShown } = useActions(billingV2Logic)
    const { currentLocation } = useValues(router)
    const [alertHidden, setAlertHidden] = useState(false)

    const showAlert = billingAlert && billingVersion === 'v2'

    useEffect(() => {
        if (showAlert) {
            reportBillingAlertShown(billingAlert)
        }
    }, [showAlert])

    if (!billingAlert || billingVersion !== 'v2' || alertHidden) {
        return null
    }

    const showButton = currentLocation.pathname !== urls.organizationBilling()

    if (!showAlert) {
        return null
    }

    const buttonProps = billingAlert.contactSupport
        ? {
              to: 'mailto:sales@posthog.com',
              children: 'Contact support',
          }
        : { to: urls.organizationBilling(), children: 'Manage billing' }

    return (
        <div className="my-4">
            <AlertMessage
                type={billingAlert.status}
                action={showButton ? buttonProps : undefined}
                onClose={billingAlert.status !== 'error' ? () => setAlertHidden(true) : undefined}
            >
                <b>{billingAlert.title}</b>
                <br />
                {billingAlert.message}
            </AlertMessage>
        </div>
    )
}
