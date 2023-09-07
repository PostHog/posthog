import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useState } from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link/Link'

export function BillingAlertsV2(): JSX.Element | null {
    const { billingAlert, rateLimits } = useValues(billingLogic)
    const { reportBillingAlertShown } = useActions(billingLogic)
    const { currentLocation } = useValues(router)
    const [alertHidden, setAlertHidden] = useState(false)

    useEffect(() => {
        if (billingAlert) {
            reportBillingAlertShown(billingAlert)
        }
    }, [billingAlert])

    let billingAlertBanner = null
    if (billingAlert && !alertHidden) {
        const showButton = currentLocation.pathname !== urls.organizationBilling()

        const buttonProps = billingAlert.contactSupport
            ? {
                to: 'mailto:sales@posthog.com',
                children: 'Contact support',
            }
            : { to: urls.organizationBilling(), children: 'Manage billing' }
        billingAlertBanner =
            <LemonBanner
                type={billingAlert.status}
                action={showButton ? buttonProps : undefined}
                onClose={billingAlert.status !== 'error' ? () => setAlertHidden(true) : undefined}
            >
                <b>{billingAlert.title}</b>
                <br />
                {billingAlert.message}
            </LemonBanner>
    }

    return (
        <div className="my-4">
            {rateLimits && (
                <LemonBanner type="error">
                    <b>Rate limits exceeded dropping {rateLimits.toString()}. See <Link to={urls.organizationBilling()}>billing page</Link> for resolutions</b>
                </LemonBanner>
            )}
            {billingAlertBanner}
        </div>
    )
}
