import { Skeleton } from 'antd'
import { useEffect, useState } from 'react'
import { PlanInterface } from '~/types'
import clsx from 'clsx'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { IconLock } from 'lib/components/icons'
import { billingLogic } from './billingLogic'
import { useActions, useValues } from 'kea'

export function Plan({
    plan,
    onSubscribe,
    currentPlan,
    canHideDetails = true,
    primaryCallToAction = true,
}: {
    plan: PlanInterface
    canHideDetails?: boolean
    onSubscribe?: (plan: PlanInterface) => void
    currentPlan?: boolean
    primaryCallToAction?: boolean
}): JSX.Element {
    const [showDetails, setShowDetails] = useState(false)
    const { planDetails, planDetailsLoading, billing } = useValues(billingLogic)
    const { loadPlanDetails } = useActions(billingLogic)

    useEffect(() => {
        loadPlanDetails(plan.key)
    }, [plan.key])

    return (
        <div className="BillingPlan border rounded p-4">
            {currentPlan && <p className="text-xs uppercase font-semibold text-muted">Current Plan</p>}
            <div className={clsx({ 'cursor-pointer': !!onSubscribe })} onClick={() => onSubscribe && onSubscribe(plan)}>
                <h3 className="text-2xl">{plan.name}</h3>
                <p>{plan.price_string}</p>
            </div>
            <div className="flex flex-col space-y-2">
                {currentPlan && !billing?.should_setup_billing && (
                    <LemonButton
                        data-attr="btn-manage-subscription"
                        data-plan={plan.key}
                        fullWidth
                        center
                        type={primaryCallToAction ? 'primary' : 'secondary'}
                        size="large"
                        to="/billing/manage"
                    >
                        Manage subscription
                    </LemonButton>
                )}
                {onSubscribe && (
                    <LemonButton
                        data-attr="btn-subscribe-now"
                        data-plan={plan.key}
                        fullWidth
                        center
                        type="primary"
                        size="large"
                        onClick={() => onSubscribe(plan)}
                    >
                        Subscribe now
                    </LemonButton>
                )}
                {canHideDetails && planDetails && (
                    <LemonButton
                        data-attr="btn-pricing-info"
                        fullWidth
                        center
                        type="tertiary"
                        onClick={() => setShowDetails(!showDetails)}
                    >
                        {showDetails ? 'Hide' : 'See more'} details
                    </LemonButton>
                )}
            </div>
            {(showDetails || !canHideDetails) && (
                <>
                    <LemonDivider className="my-4" />
                    {planDetailsLoading ? (
                        <Skeleton paragraph={{ rows: 6 }} title={false} className="mt-4" active />
                    ) : (
                        <>
                            {planDetails && (
                                <div
                                    className="BillingPlan__description"
                                    dangerouslySetInnerHTML={{ __html: planDetails }}
                                />
                            )}
                        </>
                    )}
                </>
            )}
            {currentPlan && (
                <>
                    <LemonDivider className="my-4" />
                    <div className="flex flex-row space-x-2 items-center text-muted justify-center">
                        <IconLock className="shrink-0" />
                        <p className="my-0">Your payment information is safe and secure.</p>
                    </div>
                </>
            )}
        </div>
    )
}
