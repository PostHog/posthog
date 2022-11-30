import { useValues } from 'kea'
import { billingTestLogic } from './billingTestLogic'
import { Billing } from '../../Billing'
import { AlertMessage } from 'lib/components/AlertMessage'
import './BillingLocked.scss'

export function BillingLockedV2(): JSX.Element | null {
    const { billing } = useValues(billingTestLogic)

    const productOverLimit =
        billing &&
        billing.products.find((x) => {
            return x.percentage_usage > 1
        })

    return (
        <div className="BillingLocked">
            <div className="BillingLocked__main">
                <div className="BillingLocked__content">
                    {productOverLimit && (
                        <div className="mb-4">
                            <AlertMessage type="error">
                                <b>Usage limit exceeded</b>
                                <br />
                                You have exceeded the usage limit for {productOverLimit.name}. Please upgrade your plan
                                or data loss may occur.
                            </AlertMessage>
                        </div>
                    )}
                    <Billing />
                </div>
            </div>
        </div>
    )
}
