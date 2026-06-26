import { useValues } from 'kea'

import { BillingAlertsList } from './BillingAlertsList'
import { BillingAlertCreationView, billingAlertsLogic } from './billingAlertsLogic'
import { BillingAlertWizard } from './BillingAlertWizard'

export function BillingAlerts(): JSX.Element {
    const { creationView, canAccessBilling } = useValues(billingAlertsLogic)

    if (!canAccessBilling) {
        return <div className="deprecated-space-y-4">You need billing access to manage billing alerts.</div>
    }

    if (creationView === BillingAlertCreationView.Wizard) {
        return <BillingAlertWizard />
    }

    return <BillingAlertsList />
}
