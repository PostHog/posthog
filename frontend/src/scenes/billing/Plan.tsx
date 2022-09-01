import { Skeleton } from 'antd'
import React, { useEffect, useState } from 'react'
import { PlanInterface } from '~/types'
import clsx from 'clsx'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { IconLock } from 'lib/components/icons'

export function Plan({
    plan,
    onSubscribe,
    currentPlan,
}: {
    plan: PlanInterface
    onSubscribe?: (plan: PlanInterface) => void
    currentPlan?: boolean
}): JSX.Element {
    const [detail, setDetail] = useState('')
    const [isDetailLoading, setIsDetailLoading] = useState(true)
    const [showDetails, setShowDetails] = useState(false)

    const loadPlanDetail = async (key: string): Promise<void> => {
        const response = await fetch(`/api/plans/${key}/template/`)
        if (response.ok) {
            setDetail(await response.text())
        }
        setIsDetailLoading(false)
    }

    useEffect(() => {
        loadPlanDetail(plan.key)
    }, [plan.key])

    return (
        <div className="BillingPlan border rounded p-4">
            {currentPlan && <p className="text-xs uppercase font-semibold text-muted">Current Plan</p>}
            <div className={clsx({ 'cursor-pointer': !!onSubscribe })} onClick={() => onSubscribe && onSubscribe(plan)}>
                <h3 className="text-2xl">{plan.name}</h3>
                <p>{plan.price_string}</p>
            </div>
            <div className="flex flex-col space-y-2">
                {currentPlan && (
                    <LemonButton
                        data-attr="btn-manage-subscription"
                        data-plan={plan.key}
                        fullWidth
                        center
                        type="primary"
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
                <LemonButton
                    data-attr="btn-pricing-info"
                    fullWidth
                    center
                    type="tertiary"
                    onClick={() => setShowDetails(!showDetails)}
                >
                    {showDetails ? 'Hide' : 'See more'} details
                </LemonButton>
            </div>
            {showDetails && (
                <>
                    <LemonDivider className="my-4" />
                    {isDetailLoading ? (
                        <Skeleton paragraph={{ rows: 6 }} title={false} className="mt-4" active />
                    ) : (
                        <div className="BillingPlan__description" dangerouslySetInnerHTML={{ __html: detail }} />
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
