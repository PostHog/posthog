import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import planEnterprise from 'public/plan_enterprise.svg'
import planFree from 'public/plan_free.svg'
import planPaid from 'public/plan_paid.svg'
import planStartup from 'public/plan_startup.svg'
import planYc from 'public/plan_yc.svg'

import { BillingPlan, BillingProductV2Type, StartupProgramLabel } from '~/types'

import { getUpgradeProductLink } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { paymentEntryLogic } from './paymentEntryLogic'
import { PlanComparisonModal } from './PlanComparison'

const PLAN_BADGES: Record<BillingPlan, string> = {
    [BillingPlan.Free]: planFree,
    [BillingPlan.Paid]: planPaid,
    // TODO: Add teams badge
    [BillingPlan.Teams]: planPaid,
    [BillingPlan.Enterprise]: planEnterprise,
}

const STARTUP_PROGRAM_BADGES: Record<StartupProgramLabel, string> = {
    [StartupProgramLabel.YC]: planYc,
    [StartupProgramLabel.Startup]: planStartup,
}

interface CopyVariation {
    title: string | null
    subtitle: string | null
    description: JSX.Element
    backgroundColor: string
}

const BADGE_CONFIG: Record<BillingPlan | StartupProgramLabel, CopyVariation> = {
    [BillingPlan.Free]: {
        title: 'Get the whole hog.',
        subtitle: 'Only pay for what you use.',
        backgroundColor: 'bg-danger-highlight',
        description: (
            <>
                <p>PostHog comes with all product features on every plan.</p>
                <p>Add your credit card to remove usage limits and unlock all platform features.</p>
                <p>Set billing limits as low as $0 to control your spend.</p>
                <p className="italic">P.S. You still keep the monthly free allotment for every product!</p>
            </>
        ),
    },
    [BillingPlan.Paid]: {
        title: 'Good call!',
        subtitle: "You're on the ridiculously cheap plan.",
        backgroundColor: 'bg-warning-highlight',
        description: (
            <>
                <p>PostHog comes with all product features on every plan.</p>
                <p>If you're growing like crazy, you might want to check out the enterprise plan.</p>
            </>
        ),
    },
    [BillingPlan.Teams]: {
        title: 'Good call!',
        subtitle: "You're on the team plan.",
        backgroundColor: 'bg-warning-highlight',
        description: (
            <>
                <p>PostHog comes with all product features on every plan.</p>
                <p>If you're growing like crazy, you might want to check out the enterprise plan.</p>
            </>
        ),
    },
    [BillingPlan.Enterprise]: {
        title: 'Good call!',
        subtitle: "You're on the enterprise plan.",
        backgroundColor: 'bg-success-highlight',
        description: <p>It doesn't get any better than this!</p>,
    },
    [StartupProgramLabel.Startup]: {
        title: 'Good for you!',
        subtitle: "You're on the startup plan.",
        backgroundColor: 'bg-warning-highlight',
        description: (
            <>
                <p>PostHog comes with all product features on every plan.</p>
                <p>
                    If you're growing like crazy, you might want to check out what the enterprise plan could give you.
                </p>
            </>
        ),
    },
    [StartupProgramLabel.YC]: {
        title: 'Lucky you!',
        subtitle: "You're on the special YC plan.",
        backgroundColor: 'bg-warning-highlight',
        description: (
            <>
                <p>PostHog comes with all product features on every plan.</p>
                <p>
                    If you're growing like crazy, you might want to check out what the enterprise plan could give you.
                </p>
            </>
        ),
    },
}

export const BillingCTAHero = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { showPaymentEntryModal } = useActions(paymentEntryLogic)
    const { redirectPath, billingPlan, startupProgramLabel } = useValues(billingLogic)
    const { isPlanComparisonModalOpen, billingProductLoading } = useValues(billingProductLogic({ product }))
    const { toggleIsPlanComparisonModalOpen, setBillingProductLoading } = useActions(billingProductLogic({ product }))

    if (!billingPlan) {
        return null
    }

    const showUpgradeOptions = billingPlan === BillingPlan.Free
    const copyVariation = startupProgramLabel ? BADGE_CONFIG[startupProgramLabel] : BADGE_CONFIG[billingPlan]

    return (
        <div className={`relative rounded-lg ${copyVariation.backgroundColor}`}>
            <div className="@container p-4 relative">
                <img
                    src={startupProgramLabel ? STARTUP_PROGRAM_BADGES[startupProgramLabel] : PLAN_BADGES[billingPlan]}
                    alt={startupProgramLabel ? `${startupProgramLabel} plan badge` : `${billingPlan} plan badge`}
                    className="float-right w-[33cqw] min-w-32 max-w-48 ml-6 mb-4"
                />
                {copyVariation.title && <h1 className="mb-0">{copyVariation.title}</h1>}
                {copyVariation.subtitle && <h1 className="text-danger">{copyVariation.subtitle}</h1>}
                <div className="mt-2">{copyVariation.description}</div>
                {showUpgradeOptions && (
                    <div className="flex items-center gap-2">
                        {featureFlags[FEATURE_FLAGS.BILLING_PAYMENT_ENTRY_IN_APP] == 'test' ? (
                            <BillingUpgradeCTA
                                className="inline-block"
                                type="primary"
                                status="alt"
                                data-attr="billing-page-core-upgrade-cta"
                                disableClientSideRouting
                                loading={!!billingProductLoading}
                                onClick={() => showPaymentEntryModal()}
                            >
                                Upgrade now
                            </BillingUpgradeCTA>
                        ) : (
                            <BillingUpgradeCTA
                                className="inline-block"
                                to={getUpgradeProductLink({
                                    product,
                                    redirectPath,
                                })}
                                type="primary"
                                status="alt"
                                data-attr="billing-page-core-upgrade-cta"
                                disableClientSideRouting
                                loading={!!billingProductLoading}
                                onClick={() => setBillingProductLoading(product.type)}
                            >
                                Upgrade now
                            </BillingUpgradeCTA>
                        )}
                        <LemonButton
                            className="inline-block"
                            onClick={() => toggleIsPlanComparisonModalOpen()}
                            type="primary"
                        >
                            Compare plans
                        </LemonButton>
                    </div>
                )}
            </div>
            {showUpgradeOptions && (
                <PlanComparisonModal
                    product={product}
                    title="Compare our plans"
                    includeAddons={false}
                    modalOpen={isPlanComparisonModalOpen}
                    onClose={() => toggleIsPlanComparisonModalOpen()}
                />
            )}
        </div>
    )
}
