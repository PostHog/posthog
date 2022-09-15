import React, { useState } from 'react'
import { PlanInterface } from '~/types'
import clsx from 'clsx'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { IconLock } from 'lib/components/icons'
import { billingLogic } from './billingLogic'
import { useValues } from 'kea'

const planDetailsMap = {
    standard: (
        <>
            <ul>
                <li>
                    <b>Unlimited</b> event allocation. Pay only for what you use.
                </li>
                <li>
                    <b>Unlimited</b> tracked users
                </li>
                <li>
                    <b>Unlimited</b> team members
                </li>
                <li>
                    <b>Unlimited</b> projects
                </li>
                <li>
                    <b>7 years</b> of data retention
                    <span className="disclaimer">
                        <a href="#starter-disclaimer-1">1</a>
                    </span>
                </li>
                <li>
                    <b>All core analytics features</b>
                </li>
                <li>Correlation analysis & advanced paths</li>
                <li>
                    Recordings with unlimited storage
                    <span className="disclaimer">
                        <a href="#starter-disclaimer-2">2</a>
                    </span>
                </li>
                <li>Feature flags</li>
                <li>Plugins &amp; other integrations</li>
                <li>Zapier integration</li>
                <li>Google SSO</li>
                <li>Export to data lakes</li>
                <li>Community, Slack &amp; Email support</li>
            </ul>
            <div className="disclaimer-details">
                <div id="starter-disclaimer-1">
                    1. Data may be moved to cold storage after 12 months. Queries that involve data in cold storage can
                    take longer than normal to run.
                </div>
                <div id="starter-disclaimer-2">
                    2. While there is no restriction on session recording storage, session recording information is
                    captured and stored as normal events and therefore billed as such.
                </div>
            </div>
        </>
    ),
}

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
    const { billing } = useValues(billingLogic)

    const planDetails = planDetailsMap[plan.key]

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
            {(showDetails || !canHideDetails) && planDetails && (
                <>
                    <LemonDivider className="my-4" />
                    <>{planDetails && <div className="BillingPlan__description">{planDetails}</div>}</>
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
