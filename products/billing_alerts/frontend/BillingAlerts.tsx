import { useValues } from 'kea'

import { BillingAlertEditor } from './BillingAlertEditor'
import { BillingAlertsList } from './BillingAlertsList'
import { billingAlertsLogic } from './billingAlertsLogic'

export function BillingAlerts(): JSX.Element {
    const { canAccessBilling, selectedAlert, isEditorOpen } = useValues(billingAlertsLogic)

    if (!canAccessBilling) {
        return <div>You need billing access to manage billing alerts.</div>
    }
    if (isEditorOpen) {
        return <BillingAlertEditor alert={selectedAlert} />
    }
    return <BillingAlertsList />
}
