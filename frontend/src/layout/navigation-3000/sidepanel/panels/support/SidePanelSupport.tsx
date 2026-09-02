import { useActions, useValues } from 'kea'
import React from 'react'

import { IconExpand45, IconFeatures, IconHelmet, IconMap, IconWarning } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { incidentStatusLogic } from 'lib/components/HelpMenu/incidentStatusLogic'
import {
    DEFAULT_PAID_RESPONSE_TIME,
    PAY_AS_YOU_GO_RESPONSE_TIME,
    getCurrentSupportPlan,
    getSupportResponseTimeFeature,
} from 'lib/components/Support/supportResponseTime'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { BillingPlan, BillingType, SidePanelTab } from '~/types'

import { SidePanelTickets } from 'products/conversations/frontend/components/SidePanel/SidePanelTickets'
import { sidepanelTicketsLogic } from 'products/conversations/frontend/components/SidePanel/sidepanelTicketsLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { sidePanelStateLogic } from '../../sidePanelStateLogic'

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

const StatusPageAlert = (): JSX.Element | null => {
    const { status, statusDescription, statusPageUrl } = useValues(incidentStatusLogic)

    if (status === 'operational') {
        return null
    }

    const description = statusDescription || 'Active incident'

    const severityClass = status.includes('outage')
        ? 'bg-danger-highlight border-danger'
        : 'bg-warning-highlight border-warning'

    return (
        <div className={`border rounded p-3 mb-3 ${severityClass}`}>
            <div className="flex items-start gap-2">
                <IconWarning className="text-warning w-5 h-5 shrink-0 mt-0.5" />
                <div className="flex-1">
                    <p className="font-semibold mb-1">
                        <Link to={statusPageUrl} target="_blank">
                            {description}
                        </Link>
                    </p>
                    <div className="text-sm">
                        <p className="mb-1">We're aware of an issue that may be affecting your PostHog experience.</p>
                        <p className="mb-0">
                            You may wish to check our{' '}
                            <Link to={statusPageUrl} target="_blank">
                                current status
                            </Link>{' '}
                            before contacting support.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    )
}

// In order to set these turn on the `support-message-override` feature flag.

//Support offsite messaging
const SUPPORT_MESSAGE_OVERRIDE_TITLE = "We're catching up on our support queue"
const SUPPORT_MESSAGE_OVERRIDE_BODY =
    'Our support engineers recently attended an offsite to make long-term enhancements to our support process. As a result, our response times are slightly delayed for some inquiries. Thanks for your patience as we work to get caught up!'

//Support Christmas messaging
//const SUPPORT_MESSAGE_OVERRIDE_TITLE = '🎄 🎅 Support during the holidays 🎁 ⛄'
//const SUPPORT_MESSAGE_OVERRIDE_BODY =
//    "We're offering reduced support while we celebrate the holidays. Responses may be slower than normal over the holiday period (22nd December to the 5th January). Thanks for your patience!"

const SupportMessageOverride = (): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.SUPPORT_MESSAGE_OVERRIDE]) {
        return null
    }

    return (
        <div className="border bg-surface-primary p-2 rounded gap-2 mb-3">
            <strong>{SUPPORT_MESSAGE_OVERRIDE_TITLE}</strong>
            <p className="mt-2 mb-0">{SUPPORT_MESSAGE_OVERRIDE_BODY}</p>
        </div>
    )
}

// Table shown to free users on Help panel, instead of email button
// Support response times are pulled dynamically from billing plans (product.features) where available
const SupportResponseTimesTable = ({
    billing,
    isCompact = false,
}: {
    billing?: BillingType | null
    isCompact?: boolean
}): JSX.Element => {
    const { supportPlans, billingPlan } = useValues(billingLogic)
    const { user } = useValues(userLogic)

    const hasBoostTrial = billing?.trial?.status === 'active' && billing.trial?.target === 'boost'
    const hasScaleTrial = billing?.trial?.status === 'active' && billing.trial?.target === 'scale'
    const hasEnterpriseTrial = billing?.trial?.status === 'active' && billing.trial?.target === 'enterprise'

    const hasExpiredTrial = billing?.trial?.status === 'expired'
    const expiredTrialDate = hasExpiredTrial ? dayjs(billing?.trial?.expires_at) : null
    const currentPlan = getCurrentSupportPlan({
        billing,
        billingPlan,
        organizationId: user?.organization?.id,
    })

    const plansToDisplay: {
        name: string
        current_plan: boolean | undefined
        features: any[]
        plan_key: string
        link?: string
        legacy_product?: boolean | null
    }[] = [
        {
            name: 'Free',
            current_plan: currentPlan === BillingPlan.Free,
            features: [{ note: 'Community support only' }],
            plan_key: BillingPlan.Free,
            link: 'https://posthog.com/questions',
        },
        {
            name: 'Pay-as-you-go',
            current_plan: currentPlan === BillingPlan.Paid,
            features: [{ note: PAY_AS_YOU_GO_RESPONSE_TIME }],
            plan_key: BillingPlan.Paid,
        },
        {
            name: 'Boost',
            current_plan: currentPlan === BillingPlan.Boost,
            features: [getSupportResponseTimeFeature(supportPlans, 'Boost') || { note: DEFAULT_PAID_RESPONSE_TIME }],
            plan_key: BillingPlan.Boost,
        },
        ...(billingPlan === BillingPlan.Teams
            ? [
                  {
                      name: 'Teams',
                      current_plan: currentPlan === BillingPlan.Teams,
                      features: [
                          getSupportResponseTimeFeature(supportPlans, 'Teams') || { note: DEFAULT_PAID_RESPONSE_TIME },
                      ],
                      plan_key: BillingPlan.Teams,
                      legacy_product: true,
                  },
              ]
            : []),
        {
            name: 'Scale',
            current_plan: currentPlan === BillingPlan.Scale,
            features: [getSupportResponseTimeFeature(supportPlans, 'Scale') || { note: DEFAULT_PAID_RESPONSE_TIME }],
            plan_key: BillingPlan.Scale,
        },
        {
            name: 'Enterprise',
            current_plan: currentPlan === BillingPlan.Enterprise,
            features: [
                getSupportResponseTimeFeature(supportPlans, 'Enterprise') || { note: DEFAULT_PAID_RESPONSE_TIME },
            ],
            plan_key: BillingPlan.Enterprise,
        },
    ]

    return (
        <div className="grid grid-cols-2 border rounded *:px-2 *:py-0.5 bg-surface-primary mb-2">
            {plansToDisplay.map((plan, index) => {
                const isBold = plan.current_plan

                const responseNote = plan.features.find((f: any) => f.note)?.note

                return (
                    <React.Fragment key={plan.plan_key}>
                        <div
                            className={`${index > 0 ? 'border-t' : ''} col-span-1 ${isBold ? 'font-semibold' : ''}`}
                            data-attr="support-plan-name"
                        >
                            <span className={`${isCompact ? '' : 'text-sm'}`}>
                                {plan.name}
                                {plan.legacy_product && (
                                    <span className="text-muted text-xs font-normal"> (legacy)</span>
                                )}
                                {isBold && ' '}
                                {isBold && <span className="text-muted text-xs font-normal">(your plan)</span>}
                            </span>
                        </div>
                        <div
                            className={`${index > 0 ? 'border-t' : ''} col-span-1 text-right ${
                                isBold ? 'font-semibold' : ''
                            }`}
                            data-attr="support-response-time"
                        >
                            <span className={`${isCompact ? '' : 'text-sm'}`}>
                                {!responseNote && plan.link ? (
                                    <Link to={plan.link}>Community forum</Link>
                                ) : (
                                    responseNote || 'Community support only'
                                )}
                            </span>
                        </div>
                    </React.Fragment>
                )
            })}

            {/* Display expired trial information */}
            {!(hasBoostTrial || hasScaleTrial || hasEnterpriseTrial) && hasExpiredTrial && expiredTrialDate && (
                <>
                    <div className="border-t text-muted col-span-2">Trial expired</div>
                </>
            )}

            {/* Display active trial information integrated into the table */}
            {(hasBoostTrial || hasScaleTrial || hasEnterpriseTrial) && (
                <>
                    <div className="font-bold border-t">Your trial</div>
                    <div className="font-bold border-t text-right">{DEFAULT_PAID_RESPONSE_TIME}</div>
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
    const { preflight } = useValues(preflightLogic)
    useValues(userLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { billing, billingLoading, billingPlan } = useValues(billingLogic)
    const { tickets, canCreateTicket, view, currentTicket } = useValues(sidepanelTicketsLogic)

    const isCloudOrDev = preflight?.cloud || process.env.NODE_ENV === 'development'
    const showMaxAI = isCloudOrDev
    const isBillingLoaded = !billingLoading && billing !== undefined
    // Free plans can't open new tickets, but tickets they already have (billing questions, PostHog AI
    // bug reports) stay readable and repliable here
    const showTickets = isCloudOrDev && (canCreateTicket || tickets.length > 0)

    return (
        <div className="SidePanelSupport contents">
            <SidePanelContentContainer>
                <SidePanelPaneHeader showCloseButton={false} title="Support">
                    {showTickets && (
                        <LemonButton
                            size="xsmall"
                            icon={<IconExpand45 />}
                            to={urls.myTickets(view === 'ticket' ? currentTicket?.id : undefined)}
                            onClick={() => closeSidePanel()}
                            tooltip="View your tickets full screen"
                            // LemonButton's tooltip→aria-label fallback only applies to plain buttons,
                            // not links (`to` renders a Link), so an icon-only link needs it explicitly
                            aria-label="View your tickets full screen"
                            data-attr="support-panel-expand-tickets"
                        />
                    )}
                </SidePanelPaneHeader>
                <div className="p-0 justify-start flex-none px-1 max-w-160 w-full mx-auto flex flex-col">
                    {showMaxAI && isBillingLoaded && (
                        <Section title="Ask PostHog AI">
                            <div>
                                <p>PostHog AI can now answer 80%+ of the support questions we receive! Nice.</p>
                                <p>
                                    Let PostHog AI read 100s of pages of docs for you, write SQL queries and
                                    expressions, regex patterns, etc.
                                </p>
                                <LemonButton
                                    type="primary"
                                    fullWidth
                                    center
                                    onClick={() => {
                                        openSidePanel(SidePanelTab.Max)
                                    }}
                                    targetBlank={false}
                                    className="mt-2"
                                >
                                    Chat with PostHog AI
                                </LemonButton>
                            </div>
                        </Section>
                    )}

                    {showTickets && isBillingLoaded && (
                        <Section title={canCreateTicket ? 'Contact us' : 'Your tickets'}>
                            <StatusPageAlert />
                            <SupportMessageOverride />
                            <p>
                                {canCreateTicket
                                    ? "Can't find what you need and PostHog AI unable to help? Message our support engineers."
                                    : 'You can keep replying to tickets you already have open.'}
                            </p>
                            <SidePanelTickets />
                        </Section>
                    )}

                    {!showTickets && isBillingLoaded && (
                        <Section title="">
                            <h3>Can't find what you need in the docs?</h3>
                            <p>
                                With the free plan you can ask the community via the link below, or explore your upgrade
                                choices to message our support engineers.
                            </p>
                        </Section>
                    )}

                    {/* Community forum */}
                    <Section title="Ask the community">
                        <p>
                            Questions about features, how-tos, or use cases? There are thousands of discussions in our
                            community forums.
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
                    <SupportResponseTimesTable billing={billing} isCompact={true} />
                    {billingPlan !== BillingPlan.Enterprise && (
                        <div className="flex justify-end">
                            <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>
                                Upgrade support plan
                            </Link>
                        </div>
                    )}

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
                                    to="https://posthog.com/roadmap?idea=new"
                                    icon={<IconFeatures />}
                                    targetBlank
                                >
                                    Request a feature
                                </LemonButton>
                            </li>
                        </ul>
                    </Section>
                </div>
            </SidePanelContentContainer>
        </div>
    )
}
