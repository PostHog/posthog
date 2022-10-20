import { useValues } from 'kea'
import { router } from 'kea-router'
import { billingLogic } from 'scenes/billing/v2/billingLogic'
import { urls } from 'scenes/urls'
import { AlertMessage } from './AlertMessage'

export function BillingAlertsV2(): JSX.Element | null {
    const { billingAlert, billingVersion } = useValues(billingLogic)
    const { currentLocation } = useValues(router)

    if (!billingAlert || billingVersion !== 'v2') {
        return null
    }

    const showButton = currentLocation.pathname !== urls.organizationBilling()

    return (
        <div className="my-4">
            <AlertMessage
                type={billingAlert.status}
                action={showButton ? { to: urls.organizationBilling(), children: 'Setup billing' } : undefined}
            >
                <b>{billingAlert.title}</b>
                <br />
                {billingAlert.message}
            </AlertMessage>
        </div>
    )
}
