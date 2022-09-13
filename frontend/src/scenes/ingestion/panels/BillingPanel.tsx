import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import BlushingHog from 'public/blushing-hog.png'
import { BillingEnrollment } from 'scenes/billing/BillingEnrollment'
import { LemonDivider } from '@posthog/lemon-ui'
import { IconOpenInNew } from 'lib/components/icons'
import { billingLogic } from 'scenes/billing/billingLogic'
import { Plan } from 'scenes/billing/Plan'

export function BillingPanel(): JSX.Element {
    const { completeOnboarding } = useActions(ingestionLogic)
    const { reportIngestionContinueWithoutBilling } = useActions(eventUsageLogic)
    const { billing } = useValues(billingLogic)

    return (
        <CardContainer>
            {(!billing?.plan || billing.should_setup_billing) && (
                <div className="text-left flex flex-col space-y-4">
                    <h1 className="ingestion-title">Add payment method</h1>
                    <p>
                        Your first million events every month are free. We'll let you know if you exceed this, so you
                        never get an unexpected bill.
                    </p>
                    <div className="billing-pricing-explanation-box">
                        <div className="p-4">
                            <p className="text-xs uppercase my-0">How pricing works</p>
                            <h1 className="ingestion-title">Pay per event sent to PostHog.</h1>
                            <h1 className="ingestion-title text-danger">Get access to all features.</h1>
                            <p className="mt-2 mb-0">
                                Product analytics, session recording, feature flags, a/b testing, and more.
                            </p>
                        </div>
                        <div className="billing-hog">
                            <img src={BlushingHog} alt="Blushing Hog" className="billing-hog-img" />
                        </div>
                    </div>
                    <BillingEnrollment />
                    <div>
                        <h3 className="font-bold">No surprise bills</h3>
                        <p>We'll notify you if you're forecasted to exceed the free threshold.</p>
                        <h3 className="font-bold">You're in control</h3>
                        <p>Set event limits for your project, so costs stay within budget.</p>
                    </div>
                    <LemonDivider thick dashed />
                    <a href="https://posthog.com/pricing" target="_blank">
                        <LemonButton fullWidth center type="secondary" size="large" icon={<IconOpenInNew />}>
                            View pricing
                        </LemonButton>
                    </a>
                    <LemonButton
                        size="large"
                        fullWidth
                        center
                        type="tertiary"
                        onClick={() => {
                            completeOnboarding()
                            reportIngestionContinueWithoutBilling()
                        }}
                    >
                        Skip for now
                    </LemonButton>
                </div>
            )}
            {billing?.plan && !billing?.should_setup_billing && (
                <div className="flex flex-col space-y-4">
                    <h1 className="ingestion-title">You're good to go!</h1>
                    <Plan plan={billing.plan} currentPlan canHideDetails={false} primaryCallToAction={false} />
                    <LemonButton
                        size="large"
                        fullWidth
                        center
                        type="primary"
                        onClick={() => {
                            completeOnboarding()
                        }}
                    >
                        Complete
                    </LemonButton>
                </div>
            )}
        </CardContainer>
    )
}
