import { Card, Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import { PlanInterface } from '~/types'
import { billingLogic } from './billingLogic'
import { Plan } from './Plan'

export function BillingEnrollment(): JSX.Element | null {
    const { plans, plansLoading, billingSubscriptionLoading } = useValues(billingLogic)
    const { subscribe } = useActions(billingLogic)

    const handleBillingSubscribe = (plan: PlanInterface): void => {
        subscribe(plan.key)
    }

    if (!plans.length && !plansLoading) {
        // If there are no plans to which enrollment is available, no point in showing the component
        return null
    }

    return plansLoading || billingSubscriptionLoading ? (
        <Card>
            <Skeleton active />
        </Card>
    ) : (
        <div className="flex flex-row space-x-2 justify-center">
            {plans.map((plan: PlanInterface) => (
                <Plan key={plan.key} plan={plan} onSubscribe={handleBillingSubscribe} canHideDetails={false} />
            ))}
        </div>
    )
}
