import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

export function BillingAlertsV2(): JSX.Element | null {
    const { billingAlert } = useValues(billingLogic)
    const { reportBillingAlertShown, reportBillingAlertActionClicked } = useActions(billingLogic)
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

    const showButton =
        billingAlert.action || billingAlert.contactSupport || currentLocation.pathname !== urls.organizationBilling()

    const buttonProps = billingAlert.action
        ? billingAlert.action
        : billingAlert.contactSupport
        ? {
              to: 'mailto:sales@posthog.com',
              children: billingAlert.buttonCTA || 'Contact support',
              onClick: () => reportBillingAlertActionClicked(billingAlert),
          }
        : {
              to: urls.organizationBilling(),
              children: 'Manage billing',
              onClick: () => reportBillingAlertActionClicked(billingAlert),
          }

    return (
        <div className="my-4">
            <LemonBanner
                type={billingAlert.status}
                action={showButton ? buttonProps : undefined}
                onClose={billingAlert.status !== 'error' ? () => setAlertHidden(true) : undefined}
                dismissKey={billingAlert.dismissKey}
            >
                <b>{billingAlert.title}</b>
                <br />
                {billingAlert.message}
            </LemonBanner>
        </div>
    )
}
