import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { Plan } from './Plan'
import { CurrentUsage } from './CurrentUsage'
import { BillingEnrollment } from './BillingEnrollment'
import './Billing.scss'
import { billingLogic } from './billingLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { AlertMessage } from 'lib/components/AlertMessage'
import { useValues } from 'kea'

export const scene: SceneExport = {
    component: Billing,
    logic: billingLogic,
}

export function Billing(): JSX.Element {
    const { billing, isSmallScreen } = useValues(billingLogic)

    return (
        <div className="flex flex-col space-y-6">
            <PageHeader title="Billing &amp; usage" />
            <LemonDivider />
            {billing?.should_setup_billing && (
                <AlertMessage
                    type="warning"
                    action={{
                        children: billing.subscription_url ? (
                            <a href={billing.subscription_url}>
                                <LemonButton>Finish setup</LemonButton>
                            </a>
                        ) : undefined,
                    }}
                >
                    Your plan is <b>currently inactive</b> as you haven't finished setting up your billing information.
                </AlertMessage>
            )}
            {isSmallScreen ? (
                <div className="flex flex-col space-y-4">
                    <CurrentUsage />
                    {billing?.plan ? <Plan plan={billing.plan} currentPlan /> : <BillingEnrollment />}
                </div>
            ) : (
                <div className="flex flex-row space-x-4">
                    <div className="w-2/3">
                        <CurrentUsage />
                    </div>
                    <div className="w-1/3">
                        {billing?.plan ? <Plan plan={billing.plan} currentPlan /> : <BillingEnrollment />}
                    </div>
                </div>
            )}
        </div>
    )
}
