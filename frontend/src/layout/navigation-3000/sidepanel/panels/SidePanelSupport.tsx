import { IconFeatures, IconHelmet, IconMap } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, BillingFeatureType, BillingType, ProductKey, SidePanelTab } from '~/types'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelLogic } from '../sidePanelLogic'

const Section = ({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement => {
    return (
        <section className="mb-6">
            <>
                <h3>{title}</h3>
                {children}
            </>
        </section>
    )
}

// In order to set these turn on the `support-message-override` feature flag.

//Support offsite messaging
const SUPPORT_MESSAGE_OVERRIDE_TITLE = "We're making improvements:"
const SUPPORT_MESSAGE_OVERRIDE_BODY =
    "Many of our support engineers are attending an offsite (from 12th to 16th May) so we can make long-term enhancements. We're working different hours, so non-urgent inquiries without priority support may experience a slight delay. We'll be back to full speed from the 19th!"

//Support Christmas messaging
//const SUPPORT_MESSAGE_OVERRIDE_TITLE = '🎄 🎅 Support during the holidays 🎁 ⛄'
//const SUPPORT_MESSAGE_OVERRIDE_BODY = "We're offering reduced support while we celebrate the holidays. Responses may be slower than normal over the holiday period (23rd December to the 6th January), and between the 25th and 27th of December we'll only be responding to critical issues. Thanks for your patience!"

// Table shown to free users on Help panel, instead of email button
// Support response times are pulled dynamically from billing plans (product.features) where available
const SupportResponseTimesTable = ({
    billing,
    hasActiveTrial,
    isCompact = false,
}: {
    billing?: BillingType | null
    hasActiveTrial?: boolean
    isCompact?: boolean
}): JSX.Element => {
    const { supportPlans } = useValues(billingLogic)

    // Check if Teams add-on is active using both methods
    const platformAndSupportProduct = billing?.products?.find((p) => p.type === 'platform_and_support')
    const hasTeamsAddon = platformAndSupportProduct?.addons?.find((a) => a.type === 'teams' && a.subscribed)
    const hasTeamsAddonAlt = supportPlans?.some((plan) => plan.name === 'Teams add-on' && plan.current_plan === true)
    const teamsAddonActive = Boolean(hasTeamsAddon || hasTeamsAddonAlt)

    // Check for enterprise plan
    const hasEnterprisePlan =
        billing?.products?.some((p) => p.type === 'enterprise') ||
        platformAndSupportProduct?.plans?.some((a) => a.current_plan && a.plan_key?.includes('enterprise'))

    // Check for expired trials
    const hasExpiredTrial = billing?.trial?.status === 'expired'

    // Get expiry date for expired trials
    const expiredTrialDate = hasExpiredTrial ? dayjs(billing?.trial?.expires_at) : null

    // Get support response time feature from plan
    const getResponseTimeFeature = (planName: string): BillingFeatureType | undefined => {
        // Find the plan in supportPlans
        const plan = supportPlans?.find((p) => p.name === planName)

        // Return the support_response_time feature if found
        return plan?.features?.find((f) => f.key === AvailableFeature.SUPPORT_RESPONSE_TIME)
    }

    // Create plans array from billing data - directly determine current_plan status here
    const plansToDisplay: {
        name: string
        current_plan: boolean | undefined
        features: any[]
        plan_key: string
        link?: string
    }[] = [
        {
            name: 'Totally free',
            current_plan: billing?.subscription_level === 'free' && !hasActiveTrial && !hasEnterprisePlan,
            features: [{ note: 'Community support only' }],
            plan_key: 'free',
            link: 'https://posthog.com/questions',
        },
        {
            name: 'Ridiculously cheap',
            current_plan:
                billing?.subscription_level === 'paid' && !teamsAddonActive && !hasEnterprisePlan && !hasActiveTrial,
            features: [{ note: '2 business days' }],
            plan_key: 'paid',
        },
        {
            name: 'Teams add-on',
            current_plan: teamsAddonActive && !hasActiveTrial,
            features: [
                getResponseTimeFeature('Teams add-on') || {
                    note: '1 business day',
                },
            ],
            plan_key: 'teams',
        },
        {
            name: 'Enterprise plan',
            current_plan: hasEnterprisePlan && !hasActiveTrial,
            features: [
                getResponseTimeFeature('Enterprise plan') || {
                    note: '1 business day',
                },
            ],
            plan_key: 'enterprise',
        },
    ]

    return (
        <div
            className={`grid grid-cols-2 border rounded [&_>*]:px-2 [&_>*]:py-0.5 ${
                isCompact ? 'mb-4' : 'mb-6'
            } bg-surface-primary ${isCompact ? 'pt-4' : ''}`}
        >
            <div
                className={`col-span-full flex justify-between ${
                    isCompact ? 'py-1' : 'items-center px-2 py-2 border-b'
                }`}
            >
                <strong>Avg support response times</strong>
                <div>
                    <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>Upgrade</Link>
                </div>
            </div>

            {plansToDisplay.map((plan) => {
                const isBold = plan.current_plan

                const responseNote = plan.features.find((f: any) => f.note)?.note

                const formattedResponseTime = responseNote
                    ? responseNote === '2 days' || responseNote === '24 hours'
                        ? '2 business days'
                        : responseNote === '1 day' || responseNote === '12 hours'
                        ? '1 business day'
                        : responseNote
                    : 'Community support only'

                return (
                    <React.Fragment key={plan.plan_key}>
                        <div
                            className={`border-t col-span-1 ${isBold ? 'font-semibold' : ''}`}
                            data-attr="support-plan-name"
                        >
                            <span className={`${isCompact ? '' : 'text-sm'}`}>
                                {plan.name}
                                {isBold && ' '}
                                {isBold && <span className="text-muted text-xs font-normal">(your plan)</span>}
                            </span>
                        </div>
                        <div
                            className={`border-t col-span-1 text-right ${isBold ? 'font-semibold' : ''}`}
                            data-attr="support-response-time"
                        >
                            <span className={`${isCompact ? '' : 'text-sm'}`}>
                                {formattedResponseTime === 'Community support only' && plan.link ? (
                                    <Link to={plan.link}>Community forum</Link>
                                ) : (
                                    formattedResponseTime
                                )}
                            </span>
                        </div>
                    </React.Fragment>
                )
            })}

            {/* Display expired trial information */}
            {!hasActiveTrial && hasExpiredTrial && expiredTrialDate && (
                <>
                    <div className="border-t text-muted col-span-2">Trial expired</div>
                </>
            )}

            {/* Display active trial information integrated into the table */}
            {hasActiveTrial && (
                <>
                    <div className="font-bold border-t">Your trial</div>
                    <div className="font-bold border-t text-right">1 business day</div>
                    {billing?.trial?.expires_at && (
                        <div className="col-span-2 text-sm">
                            (Trial expires {dayjs(billing.trial.expires_at).format('MMMM D, YYYY')})
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

export function SidePanelSupport(): JSX.Element {
    // We need preflightLogic and userLogic for debugBilling to work properly
    const { preflight } = useValues(preflightLogic)
    useValues(userLogic)
    const { isEmailFormOpen, title: supportPanelTitle } = useValues(supportLogic)
    const { closeEmailForm, openEmailForm, closeSupportForm } = useActions(supportLogic)
    const { billing, billingLoading } = useValues(billingLogic)
    const { openSidePanel } = useActions(sidePanelLogic)

    // Check for support access - paid plans or active trials only
    const canEmail =
        billing?.subscription_level === 'paid' ||
        billing?.subscription_level === 'custom' ||
        (!!billing?.trial?.status && billing.trial.status === 'active')

    // Check if we're on a paid plan or active trial
    const hasActiveTrial = !!billing?.trial?.status && billing.trial.status === 'active'

    // Show email support only to paid/trial users on cloud or in development
    const showEmailSupport = (preflight?.cloud || process.env.NODE_ENV === 'development') && canEmail

    // Show Max AI to all cloud users regardless of plan or in development
    const showMaxAI = preflight?.cloud || process.env.NODE_ENV === 'development'

    // Ensure billing data is loaded before showing support options
    const isBillingLoaded = !billingLoading && billing !== undefined

    const handleOpenEmailForm = (): void => {
        // Only allow email form opening if user has access
        if (showEmailSupport && isBillingLoaded) {
            openEmailForm()
        }
    }

    // Define SupportFormBlock component here, with access to debugBilling
    const SupportFormBlock = ({
        onCancel,
        hasActiveTrial,
    }: {
        onCancel: () => void
        hasActiveTrial?: boolean
    }): JSX.Element => {
        const { featureFlags } = useValues(featureFlagLogic)

        return (
            <Section title="Email an engineer">
                <SupportForm />
                <LemonButton
                    form="support-modal-form"
                    htmlType="submit"
                    type="primary"
                    data-attr="submit"
                    fullWidth
                    center
                    className="mt-4"
                >
                    Submit
                </LemonButton>
                <LemonButton
                    form="support-modal-form"
                    type="secondary"
                    onClick={onCancel}
                    fullWidth
                    center
                    className="mt-2 mb-4"
                >
                    Cancel
                </LemonButton>

                <br />

                {featureFlags[FEATURE_FLAGS.SUPPORT_MESSAGE_OVERRIDE] ? (
                    <div className="border bg-surface-primary p-2 rounded gap-2">
                        <strong>{SUPPORT_MESSAGE_OVERRIDE_TITLE}</strong>
                        <p className="mt-2 mb-0">{SUPPORT_MESSAGE_OVERRIDE_BODY}</p>
                    </div>
                ) : (
                    <>
                        <div className="mb-2">
                            <strong>Support is open Monday - Friday</strong>
                        </div>

                        {/* Show response time information from billing plans */}
                        <SupportResponseTimesTable billing={billing} hasActiveTrial={hasActiveTrial} isCompact={true} />
                    </>
                )}
            </Section>
        )
    }

    return (
        <div className="SidePanelSupport">
            <SidePanelPaneHeader title={isEmailFormOpen ? supportPanelTitle : 'Help'} />

            <div className="overflow-y-auto flex flex-col h-full">
                <div className="p-3 max-w-160 w-full mx-auto flex-1 flex flex-col justify-center">
                    {isEmailFormOpen && showEmailSupport && isBillingLoaded ? (
                        <SupportFormBlock
                            onCancel={() => {
                                closeEmailForm()
                                closeSupportForm()
                            }}
                            hasActiveTrial={hasActiveTrial}
                        />
                    ) : (
                        <>
                            {/* Max AI section - show for all cloud users */}
                            {showMaxAI && isBillingLoaded && (
                                <Section title="Ask Max AI">
                                    <div>
                                        <p>Max AI can now answer 80%+ of the support questions we receive! Nice.</p>
                                        <p>
                                            Let Max read 100s of pages of docs for you, write SQL queries and
                                            expressions, regex patterns, etc.
                                        </p>
                                        <LemonButton
                                            type="primary"
                                            fullWidth
                                            center
                                            onClick={() => {
                                                openSidePanel(
                                                    SidePanelTab.Docs,
                                                    '/docs/new-to-posthog/understand-posthog?chat=open'
                                                )
                                            }}
                                            targetBlank={false}
                                            className="mt-2"
                                        >
                                            Chat with Max AI
                                        </LemonButton>
                                    </div>
                                </Section>
                            )}

                            {/* Contact us section - only show for paid/trial users on cloud */}
                            {showEmailSupport && isBillingLoaded && (
                                <Section title="Contact us">
                                    <p>Can't find what you need and Max unable to help?</p>
                                    <LemonButton
                                        type="secondary"
                                        fullWidth
                                        center
                                        onClick={handleOpenEmailForm}
                                        className="mt-2"
                                        disabled={billingLoading}
                                    >
                                        {billingLoading ? 'Loading...' : 'Email our support engineers'}
                                    </LemonButton>
                                </Section>
                            )}

                            {/* For free users who can't email, show an explanation */}
                            {!showEmailSupport && isBillingLoaded && (
                                <Section title="">
                                    <h3>Can't find what you need in the docs?</h3>
                                    <p>
                                        With the totally free plan you can ask the community via the link below, or
                                        explore your upgrade choices for the ability to email a support engineer.
                                    </p>
                                </Section>
                            )}

                            {/* Community forum */}
                            <Section title="Ask the community">
                                <p>
                                    Questions about features, how-tos, or use cases? There are thousands of discussions
                                    in our community forums.
                                </p>
                                <LemonButton
                                    type="secondary"
                                    fullWidth
                                    center
                                    to="https://posthog.com/questions"
                                    targetBlank
                                    className="mt-2"
                                >
                                    Ask the community
                                </LemonButton>
                            </Section>

                            {/* Add support hours and table */}
                            <div className="mb-2">
                                <strong>Support is open Monday - Friday</strong>
                            </div>
                            <SupportResponseTimesTable
                                billing={billing}
                                hasActiveTrial={hasActiveTrial}
                                isCompact={true}
                            />

                            {/* Share feedback section */}
                            <Section title="Share feedback">
                                <ul>
                                    <li>
                                        <LemonButton
                                            type="secondary"
                                            status="alt"
                                            to="https://posthog.com/wip"
                                            icon={<IconHelmet />}
                                            targetBlank
                                        >
                                            See what we're building
                                        </LemonButton>
                                    </li>
                                    <li>
                                        <LemonButton
                                            type="secondary"
                                            status="alt"
                                            to="https://posthog.com/roadmap"
                                            icon={<IconMap />}
                                            targetBlank
                                        >
                                            Vote on our roadmap
                                        </LemonButton>
                                    </li>
                                    <li>
                                        <LemonButton
                                            type="secondary"
                                            status="alt"
                                            to="https://github.com/PostHog/posthog/issues/new?&labels=enhancement&template=feature_request.yml"
                                            icon={<IconFeatures />}
                                            targetBlank
                                        >
                                            Request a feature
                                        </LemonButton>
                                    </li>
                                </ul>
                            </Section>
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
