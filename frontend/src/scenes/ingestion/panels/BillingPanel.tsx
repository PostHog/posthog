import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import './Panels.scss'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { LemonDivider } from '@posthog/lemon-ui'
import { billingLogic } from 'scenes/billing/billingLogic'
import { Billing } from 'scenes/billing/Billing'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export function BillingPanel(): JSX.Element {
    const { completeOnboarding } = useActions(ingestionLogic)
    const { reportIngestionContinueWithoutBilling } = useActions(eventUsageLogic)
    const { billing: billingV2, billingVersion } = useValues(billingLogic)

    if (!billingVersion || billingVersion !== 'v2') {
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
                    <Billing />

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
