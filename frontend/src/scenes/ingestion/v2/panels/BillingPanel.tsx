import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/v2/CardContainer'
import { ingestionLogicV2 } from 'scenes/ingestion/v2/ingestionLogicV2'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { BillingEnrollment } from 'scenes/billing/BillingEnrollment'
import { LemonDivider } from '@posthog/lemon-ui'
import { IconOpenInNew } from 'lib/components/icons'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingLogic as billingLogicV2 } from 'scenes/billing/v2/control/billingLogic'
import { Plan } from 'scenes/billing/Plan'
import { BillingV2 } from 'scenes/billing/v2/control/Billing'
import { BillingV2 as BillingV2Test } from 'scenes/billing/v2/test/Billing'
import { LemonSkeleton } from 'lib/components/LemonSkeleton'
import { urls } from 'scenes/urls'
import { BillingHero } from 'scenes/billing/v2/control/BillingHero'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function BillingPanel(): JSX.Element {
    const { completeOnboarding } = useActions(ingestionLogicV2)
    const { reportIngestionContinueWithoutBilling } = useActions(eventUsageLogic)
    const { billing, billingVersion } = useValues(billingLogic)
    const { billing: billingV2 } = useValues(billingLogicV2)

    const featureFlags = featureFlagLogic.findMounted()?.values?.featureFlags
    const testExperiment = featureFlags?.[FEATURE_FLAGS.BILLING_FEATURES_EXPERIMENT] === 'test'

    if (!billingVersion) {
        return (
            <CardContainer>
                <div className="space-y-4" style={{ width: 800 }}>
                    <LemonSkeleton className="w-full h-10" />
                    <LemonSkeleton className="w-full" />
                    <LemonSkeleton className="w-full" />
                    <div className="h-20" />
                    <div className="h-20" />
                    <LemonSkeleton className="w-full h-10" />
                    <LemonSkeleton className="w-full h-10" />
                </div>
            </CardContainer>
        )
    }

    if (billingVersion == 'v2') {
        return (
            <CardContainer>
                {billingV2?.has_active_subscription ? (
                    <div className="flex flex-col space-y-4">
                        <h1 className="ingestion-title">You're good to go!</h1>

                        <p>
                            Your organisation is setup for billing with premium features and the increased free tiers
                            enabled.
                        </p>
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
                ) : (
                    <div className="text-left flex flex-col space-y-4">
                        <h1 className="ingestion-title">Add payment method</h1>
                        {testExperiment ? (
                            <BillingV2Test redirectPath={urls.ingestion() + '/billing'} showCurrentUsage={false} />
                        ) : (
                            <BillingV2 redirectPath={urls.ingestion() + '/billing'} />
                        )}

                        <LemonDivider dashed />

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
            </CardContainer>
        )
    }

    return (
        <CardContainer>
            {(!billing?.plan || billing.should_setup_billing) && (
                <div className="text-left flex flex-col space-y-4">
                    <h1 className="ingestion-title">Add payment method</h1>
                    <p>
                        Your first million events every month are free. We'll let you know if you exceed this, so you
                        never get an unexpected bill.
                    </p>
                    <BillingHero />
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
