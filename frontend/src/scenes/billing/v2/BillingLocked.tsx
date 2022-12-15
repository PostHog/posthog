import { Billing } from '../Billing'
import './BillingLocked.scss'
import { BillingAlertsV2 } from 'lib/components/BillingAlertsV2'

export function BillingLockedV2(): JSX.Element | null {
    return (
        <div className="BillingLocked">
            <div className="BillingLocked__main">
                <div className="BillingLocked__content">
                    <BillingAlertsV2 />
                    <Billing />
                </div>
            </div>
        </div>
    )
}
