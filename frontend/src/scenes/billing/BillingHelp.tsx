import { useActions, useValues } from 'kea'
import { Suspense, useEffect } from 'react'

import { IconArrowLeft, IconExternal } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { billingLogic } from 'lib/logic/billing/billingLogic'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import { BillingPlan } from '~/types'

import { billingHelpLogic } from './billingHelpLogic'
import { BillingNoAccess } from './BillingNoAccess'

// Loaded on demand so the help page only ships the Wizard spend audit code when a person opens it.
const OptimizeSpendCta = lazyWithRetry(() =>
    import('./OptimizeSpendCta').then((module) => ({ default: module.OptimizeSpendCta }))
)

const PLAN_LABELS: Record<BillingPlan, string> = {
    [BillingPlan.Free]: 'the Free plan',
    [BillingPlan.Paid]: 'the Pay-as-you-go plan',
    [BillingPlan.Teams]: 'the Pay-as-you-go plan with the Teams add-on',
    [BillingPlan.Boost]: 'the Pay-as-you-go plan with the Boost add-on',
    [BillingPlan.Scale]: 'the Pay-as-you-go plan with the Scale add-on',
    [BillingPlan.Enterprise]: 'the Enterprise plan',
}

const COST_GUIDES: { key: string; label: string; url: string }[] = [
    {
        key: 'estimating-usage-costs',
        label: 'Estimate and reduce your costs',
        url: 'https://posthog.com/docs/billing/estimating-usage-costs#how-to-reduce-your-posthog-costs',
    },
    {
        key: 'product-analytics',
        label: 'Product analytics',
        url: 'https://posthog.com/docs/product-analytics/cutting-costs',
    },
    { key: 'session-replay', label: 'Session replay', url: 'https://posthog.com/docs/session-replay/cutting-costs' },
    { key: 'feature-flags', label: 'Feature flags', url: 'https://posthog.com/docs/feature-flags/cutting-costs' },
    { key: 'error-tracking', label: 'Error tracking', url: 'https://posthog.com/docs/error-tracking/cutting-costs' },
    { key: 'data-warehouse', label: 'Data warehouse', url: 'https://posthog.com/docs/data-warehouse/cutting-costs' },
]

export function BillingHelp(): JSX.Element {
    const { accountOwner, billingPlan, minimumBillingAccessLevel } = useValues(billingLogic)
    const { openSupportForm } = useActions(supportLogic)
    const { reportBillingHelpViewed, reportBillingHelpLinkClicked, reportBillingHelpContactClicked } =
        useActions(billingHelpLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: minimumBillingAccessLevel,
        scope: RestrictionScope.Organization,
    })
    const contactName = accountOwner?.name?.trim() || null
    const contactEmail = accountOwner?.email?.trim() || null
    const hasAccountContact = !!(contactName || contactEmail)

    useEffect(() => {
        reportBillingHelpViewed(hasAccountContact)
    }, [hasAccountContact]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (restrictionReason) {
        return <BillingNoAccess reason={restrictionReason} />
    }

    return (
        <div className="flex max-w-300 flex-col gap-6" data-attr="billing-help">
            <div>
                <LemonButton
                    type="tertiary"
                    size="small"
                    icon={<IconArrowLeft />}
                    to={urls.organizationBillingSection('overview')}
                    data-attr="billing-help-back"
                >
                    Back to billing overview
                </LemonButton>
                <h2 className="mt-2 mb-1">Questions about your bill?</h2>
                <p className="mb-0 text-secondary">Who to contact, how pricing works, and ways to lower your spend.</p>
            </div>

            <LemonCard hoverEffect={false} className="p-4" data-attr="billing-help-contact">
                <h3 className="mb-1">Your account contact</h3>
                {hasAccountContact ? (
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <p className="mb-0">
                            {contactName
                                ? `${contactName} looks after your account.`
                                : 'You have a dedicated account contact.'}{' '}
                            Email them with questions about your bill or plan.
                            {contactEmail && (
                                <>
                                    {' '}
                                    <Link
                                        to={`mailto:${contactEmail}`}
                                        onClick={() => reportBillingHelpContactClicked('email')}
                                    >
                                        {contactEmail}
                                    </Link>
                                </>
                            )}
                        </p>
                        {contactEmail && (
                            <LemonButton
                                type="primary"
                                to={`mailto:${contactEmail}`}
                                onClick={() => reportBillingHelpContactClicked('email')}
                                data-attr="billing-help-email-contact"
                            >
                                {contactName ? `Email ${contactName.split(' ')[0]}` : 'Email your contact'}
                            </LemonButton>
                        )}
                    </div>
                ) : (
                    <div className="flex flex-wrap items-center justify-between gap-4">
                        <p className="mb-0">
                            You don't have a dedicated account contact. Our support team answers billing questions.
                        </p>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                reportBillingHelpContactClicked('support')
                                openSupportForm({ billing_issue: true, isEmailFormOpen: true })
                            }}
                            data-attr="billing-help-chat-support"
                        >
                            Chat with support
                        </LemonButton>
                    </div>
                )}
            </LemonCard>

            <LemonCard hoverEffect={false} className="p-4" data-attr="billing-help-pricing">
                <h3 className="mb-1">How pricing works</h3>
                <p className="mb-2">
                    {billingPlan ? `You're on ${PLAN_LABELS[billingPlan]}. ` : ''}
                    Every product has a monthly free allowance. Above it you pay per unit, and the unit price drops as
                    your volume grows. A billing limit caps what a product can charge in a period.
                </p>
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        to="https://posthog.com/pricing"
                        targetBlank
                        sideIcon={<IconExternal />}
                        onClick={() => reportBillingHelpLinkClicked('pricing')}
                        data-attr="billing-help-pricing-link"
                    >
                        See pricing
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to="https://posthog.com/docs/billing/limits-alerts"
                        targetBlank
                        sideIcon={<IconExternal />}
                        onClick={() => reportBillingHelpLinkClicked('limits-alerts')}
                        data-attr="billing-help-limits-link"
                    >
                        Billing limits and alerts
                    </LemonButton>
                </div>
            </LemonCard>

            <LemonCard hoverEffect={false} className="p-4" data-attr="billing-help-guides">
                <h3 className="mb-1">Ways to lower your bill</h3>
                <p className="mb-2">
                    Most savings come from sending less data you don't use. Each guide walks through one product.
                </p>
                <ul className="mb-0 list-disc space-y-1 pl-5">
                    {COST_GUIDES.map((guide) => (
                        <li key={guide.key}>
                            <Link
                                to={guide.url}
                                target="_blank"
                                onClick={() => reportBillingHelpLinkClicked(guide.key)}
                                data-attr={`billing-help-guide-${guide.key}`}
                            >
                                {guide.label}
                            </Link>
                        </li>
                    ))}
                </ul>
            </LemonCard>

            <Suspense fallback={null}>
                <OptimizeSpendCta />
            </Suspense>
        </div>
    )
}
