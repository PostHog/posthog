import {
    IconAI,
    IconBook,
    IconChevronDown,
    IconDatabase,
    IconFeatures,
    IconGraph,
    IconHelmet,
    IconMap,
    IconMessage,
    IconPieChart,
    IconPlug,
    IconRewindPlay,
    IconStack,
    IconTestTube,
    IconToggle,
} from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { SupportForm } from 'lib/components/Support/SupportForm'
import { getPublicSupportSnippet, supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature, BillingType, ProductKey, SidePanelTab } from '~/types'

import AlgoliaSearch from '../../components/AlgoliaSearch'
import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { MaxChatInterface } from './sidePanelMaxChatInterface'
import { sidePanelStatusLogic } from './sidePanelStatusLogic'

const PRODUCTS = [
    {
        name: 'Product OS',
        slug: 'product-os',
        icon: <IconStack className="text-danger h-5 w-5" />,
    },
    {
        name: 'Product analytics',
        slug: 'product-analytics',
        icon: <IconGraph className="text-[#2F80FA] h-5 w-5" />,
    },
    {
        name: 'Web analytics',
        slug: 'web-analytics',
        icon: <IconPieChart className="text-[#36C46F] h-5 w-5" />,
    },
    {
        name: 'Session replay',
        slug: 'session-replay',
        icon: <IconRewindPlay className="text-warning h-5 w-5" />,
    },
    {
        name: 'Feature flags',
        slug: 'feature-flags',
        icon: <IconToggle className="text-[#30ABC6] h-5 w-5" />,
    },
    {
        name: 'Experiments',
        slug: 'experiments',
        icon: <IconTestTube className="text-[#B62AD9] h-5 w-5" />,
    },
    {
        name: 'Surveys',
        slug: 'surveys',
        icon: <IconMessage className="text-danger h-5 w-5" />,
    },
    {
        name: 'Data pipelines',
        slug: 'cdp',
        icon: <IconPlug className="text-[#2EA2D3] h-5 w-5" />,
    },
    {
        name: 'Data warehouse',
        slug: 'data-warehouse',
        icon: <IconDatabase className="text-[#8567FF] h-5 w-5" />,
    },
    {
        name: 'AI engineering',
        slug: 'ai-engineering',
        icon: <IconAI className="text-[#681291] dark:text-[#C170E8] h-5 w-5" />,
    },
]

const Section = ({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement => {
    return (
        <section className="mb-6">
            {title === 'Explore the docs' ? (
                <LemonCollapse
                    panels={[
                        {
                            key: 'docs',
                            header: (
                                <div className="flex items-center gap-1.5">
                                    <IconBook className="text-warning h-5 w-5" />
                                    <span>{title}</span>
                                </div>
                            ),
                            content: children,
                        },
                    ]}
                />
            ) : (
                <>
                    <h3>{title}</h3>
                    {children}
                </>
            )}
        </section>
    )
}

// In order to set these turn on the `support-message-override` feature flag.
const SUPPORT_MESSAGE_OVERRIDE_TITLE = '🎄 🎅 Support during the holidays 🎁 ⛄'
const SUPPORT_MESSAGE_OVERRIDE_BODY =
    "We're offering reduced support while we celebrate the holidays. Responses may be slower than normal over the holiday period (23rd December to the 6th January), and between the 25th and 27th of December we'll only be responding to critical issues. Thanks for your patience!"

const SupportFormBlock = ({
    onCancel,
    hasActiveTrial,
    billing,
}: {
    onCancel: () => void
    hasActiveTrial?: boolean
    billing?: BillingType | null
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
                        <strong>Support is open Monday - Friday:</strong>
                    </div>

                    {/* Pass null to use default plans with correct response time notes */}
                    <SupportResponseTimesTable
                        billing={billing}
                        hasActiveTrial={hasActiveTrial}
                        supportPlansToDisplay={null}
                        isCompact={true}
                    />
                </>
            )}
        </Section>
    )
}

// Table shown to free users on Help panel, instead of email button
const SupportResponseTimesTable = ({
    billing,
    hasActiveTrial,
    supportPlansToDisplay,
    isCompact = false,
}: {
    billing?: BillingType | null
    hasActiveTrial?: boolean
    supportPlansToDisplay?: any[] | null // Use the correct type from billingLogic
    isCompact?: boolean
}): JSX.Element => {
    const { supportPlans } = useValues(billingLogic)

    // Check if Teams add-on is active using both methods
    const platformAndSupportProduct = billing?.products?.find((p) => p.type === 'platform_and_support')
    const hasTeamsAddon = platformAndSupportProduct?.addons?.find((a) => a.type === 'teams' && a.subscribed)
    const hasTeamsAddonAlt = supportPlans?.some((plan) => plan.name === 'Teams add-on' && plan.current_plan === true)
    const teamsAddonActive = !!hasTeamsAddon || hasTeamsAddonAlt

    // Check for enterprise plan
    const hasEnterprisePlan =
        billing?.products?.some((p) => p.type === 'enterprise') ||
        platformAndSupportProduct?.plans?.some((a) => a.current_plan && a.plan_key?.includes('enterprise'))

    // Check for expired trials
    const hasOldStyleExpiredTrial = billing?.free_trial_until && billing.free_trial_until.isBefore(dayjs())
    const hasNewStyleExpiredTrial = billing?.trial?.status === 'expired'
    const hasExpiredTrial = hasOldStyleExpiredTrial || hasNewStyleExpiredTrial

    // Get expiry date for expired trials
    const expiredTrialDate = hasOldStyleExpiredTrial
        ? billing?.free_trial_until
        : hasNewStyleExpiredTrial
        ? dayjs(billing?.trial?.expires_at)
        : null

    // Create a standardized plans array that works for both cases
    const plansToDisplay = supportPlansToDisplay || [
        {
            name: 'Totally free',
            current_plan: billing?.subscription_level === 'free' && !hasActiveTrial,
            features: [{ note: 'Community support only' }],
            plan_key: 'free',
            link: 'https://posthog.com/questions',
        },
        {
            name: 'Ridiculously cheap',
            current_plan: billing?.subscription_level === 'paid' && !teamsAddonActive && !hasEnterprisePlan,
            features: [{ note: '2 days' }],
            plan_key: 'standard',
        },
        {
            name: 'Teams add-on',
            current_plan: teamsAddonActive,
            features: [{ note: '1 day' }],
            plan_key: 'teams',
        },
        {
            name: 'Enterprise',
            current_plan: hasEnterprisePlan,
            features: [{ note: '1 day' }],
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
                    <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>Explore options</Link>
                </div>
            </div>

            {plansToDisplay.map((plan) => {
                // Check if Teams add-on is active
                const isCurrentPlan =
                    plan.current_plan &&
                    (!hasTeamsAddon || plan.plan_key?.includes('addon')) &&
                    (!hasActiveTrial || plan.name !== 'Totally free') &&
                    !(billing?.subscription_level === 'paid' && plan.name === 'Totally free') &&
                    !(teamsAddonActive && plan.name === 'Ridiculously cheap') &&
                    !(hasEnterprisePlan && plan.name === 'Ridiculously cheap')

                // For Teams add-on, force it to be the current plan when it's active
                const isTeamsAddonActive = teamsAddonActive && plan.name === 'Teams add-on'

                // For Enterprise, force it to be the current plan when it's active
                const isEnterprisePlanActive =
                    hasEnterprisePlan && billing?.subscription_level === 'paid' && plan.name === 'Enterprise'

                // Check if Ridiculously cheap should show as current plan
                const isRidiculouslyCheapCurrentPlan =
                    billing?.subscription_level === 'paid' &&
                    plan.name === 'Ridiculously cheap' &&
                    !teamsAddonActive &&
                    !hasEnterprisePlan

                const isBold =
                    isCurrentPlan || isTeamsAddonActive || isEnterprisePlanActive || isRidiculouslyCheapCurrentPlan

                const responseNote = plan.features.find(
                    (f: { key?: any; note?: string }) => f.key == AvailableFeature.SUPPORT_RESPONSE_TIME || f.note
                )?.note

                const formattedResponseTime = responseNote
                    ? responseNote === '2 days' || responseNote === '24 hours'
                        ? '2 business days'
                        : responseNote === '1 day' || responseNote === '12 hours'
                        ? '1 business day'
                        : responseNote
                    : 'Community support only'

                return (
                    <React.Fragment key={`support-panel-${plan.plan_key}`}>
                        <div className={isBold ? 'font-bold' : undefined}>
                            {plan.name}
                            {isBold && plan.name !== 'Totally free' && (
                                <span className="ml-1 text-sm opacity-60">(your plan)</span>
                            )}
                        </div>
                        <div className={isBold ? 'font-bold' : undefined}>
                            {plan.link ? <Link to={plan.link}>{formattedResponseTime}</Link> : formattedResponseTime}
                        </div>
                    </React.Fragment>
                )
            })}

            {/* Display trial information integrated into the table */}
            {hasActiveTrial && (
                <>
                    <div className="font-bold border-t">Your trial</div>
                    <div className="font-bold border-t">1 business day</div>
                    {/* Show expiration date for both old-style and new-style trials */}
                    {billing?.free_trial_until && (
                        <div className="col-span-2 text-sm">
                            (Trial ends {billing.free_trial_until.format('MMMM D, YYYY')})
                        </div>
                    )}
                    {billing?.trial?.expires_at && !billing?.free_trial_until && (
                        <div className="col-span-2 text-sm">
                            (Trial ends {dayjs(billing.trial.expires_at).format('MMMM D, YYYY')})
                        </div>
                    )}
                </>
            )}

            {/* Display expired trial information */}
            {!hasActiveTrial && hasExpiredTrial && expiredTrialDate && (
                <>
                    <div className="border-t text-muted">Trial expired</div>
                    <div className="border-t text-muted">{expiredTrialDate.format('MMMM D, YYYY')}</div>
                </>
            )}
        </div>
    )
}

export const SidePanelSupport = (): JSX.Element => {
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { preflight } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { status } = useValues(sidePanelStatusLogic)
    const { billing, billingLoading } = useValues(billingLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { openEmailForm, closeEmailForm, openMaxChatInterface, closeMaxChatInterface } = useActions(theLogic)
    const { isEmailFormOpen, isMaxChatInterfaceOpen } = useValues(theLogic)

    const region = preflight?.region

    // Check if user has a paid subscription or is on an active trial
    const hasActiveTrial =
        (!!billing?.free_trial_until && billing.free_trial_until.isAfter(dayjs())) ||
        billing?.trial?.status === 'active'

    const canEmailEngineer = billing?.subscription_level !== 'free' || hasActiveTrial

    // In dev, show the support form for paid plans regardless of cloud status
    // In production, only show it for cloud users with paid plans or active trials
    // Note: The backend will validate access rights when processing support requests
    const isDevelopment = process.env.NODE_ENV === 'development'
    const showEmailSupport = isDevelopment ? canEmailEngineer : preflight?.cloud && canEmailEngineer

    // Ensure billing data is loaded before showing support options
    const isBillingLoaded = !billingLoading && billing !== undefined

    // Prevent the email form from being opened by free or self-hosted
    const handleOpenEmailForm = (): void => {
        if (showEmailSupport && isBillingLoaded) {
            openEmailForm()
        }
    }

    React.useEffect(() => {
        if (isEmailFormOpen && isBillingLoaded && !showEmailSupport) {
            closeEmailForm()
        }
    }, [isEmailFormOpen, isBillingLoaded, showEmailSupport, closeEmailForm])

    return (
        <>
            <div className="overflow-y-auto" data-attr="side-panel-support-container">
                <SidePanelPaneHeader title="Help" />
                <div className="p-3 max-w-160 w-full mx-auto">
                    {isEmailFormOpen && showEmailSupport && isBillingLoaded ? (
                        <SupportFormBlock
                            onCancel={() => closeEmailForm()}
                            hasActiveTrial={hasActiveTrial}
                            billing={billing}
                        />
                    ) : isMaxChatInterfaceOpen ? (
                        <div className="deprecated-space-y-4">
                            <MaxChatInterface />
                            <LemonButton
                                type="secondary"
                                onClick={() => closeMaxChatInterface()}
                                fullWidth
                                center
                                className="mt-2"
                            >
                                End Chat
                            </LemonButton>
                        </div>
                    ) : (
                        <>
                            <Section title="Search docs & community questions">
                                <AlgoliaSearch />
                            </Section>

                            <Section title="Explore the docs">
                                <ul className="border rounded divide-y bg-surface-primary dark:bg-transparent font-title font-medium">
                                    {PRODUCTS.map((product, index) => (
                                        <li key={index}>
                                            <Link
                                                to={`https://posthog.com/docs/${product.slug}`}
                                                className="group flex items-center justify-between px-2 py-1.5"
                                            >
                                                <div className="flex items-center gap-1.5">
                                                    {product.icon}
                                                    <span className="text-text-3000 opacity-75 group-hover:opacity-100">
                                                        {product.name}
                                                    </span>
                                                </div>
                                                <div>
                                                    <IconChevronDown className="text-text-3000 h-6 w-6 opacity-60 -rotate-90 group-hover:opacity-90" />
                                                </div>
                                            </Link>
                                        </li>
                                    ))}
                                </ul>
                            </Section>

                            {status !== 'operational' && (
                                <Section title="">
                                    <LemonBanner type={status.includes('outage') ? 'error' : 'warning'}>
                                        <div>
                                            {status.includes('outage') ? (
                                                <span>We are experiencing major issues.</span>
                                            ) : (
                                                <span>We are experiencing issues.</span>
                                            )}
                                            <LemonButton
                                                type="secondary"
                                                fullWidth
                                                center
                                                targetBlank
                                                onClick={() => openSidePanel(SidePanelTab.Status)}
                                                className="mt-2 bg-[white]"
                                            >
                                                View system status
                                            </LemonButton>
                                        </div>
                                    </LemonBanner>
                                </Section>
                            )}

                            {preflight?.cloud ? (
                                <FlaggedFeature flag={FEATURE_FLAGS.SUPPORT_SIDEBAR_MAX} match={true}>
                                    <Section title="Ask Max the Hedgehog">
                                        <div>
                                            <p>
                                                Max is PostHog's support AI who can answer support questions, help you
                                                with troubleshooting, find info in our documentation, write HogQL
                                                queries, regex expressions, etc.
                                            </p>
                                            <LemonButton
                                                type="primary"
                                                fullWidth
                                                center
                                                onClick={() => {
                                                    openMaxChatInterface()
                                                }}
                                                targetBlank={false}
                                                className="mt-2"
                                            >
                                                ✨ Chat with Max
                                            </LemonButton>
                                        </div>
                                    </Section>
                                </FlaggedFeature>
                            ) : null}

                            {!showEmailSupport && isBillingLoaded && (
                                <Section title="">
                                    <h3>Can't find what you need in the docs?</h3>
                                    <p>
                                        With the totally free plan you can ask the community via the link below, or
                                        explore your upgrade choices for the ability to email a support engineer.
                                    </p>
                                </Section>
                            )}

                            {showEmailSupport && isBillingLoaded && (
                                <Section title="Contact us">
                                    <p>Can't find what you need in the docs?</p>
                                    <LemonButton
                                        type="primary"
                                        fullWidth
                                        center
                                        onClick={handleOpenEmailForm}
                                        targetBlank
                                        className="mt-2"
                                        disabled={billingLoading}
                                    >
                                        {billingLoading ? 'Loading...' : 'Email our support engineers'}
                                    </LemonButton>
                                </Section>
                            )}

                            <Section title="Ask the community">
                                <p>
                                    Questions about features, how-tos, or use cases? There are thousands of discussions
                                    in our community forums.{' '}
                                    <Link to="https://posthog.com/questions">Ask a question</Link>
                                </p>
                            </Section>

                            {!showEmailSupport && isBillingLoaded && (
                                <SupportResponseTimesTable
                                    billing={billing}
                                    hasActiveTrial={hasActiveTrial}
                                    supportPlansToDisplay={undefined}
                                />
                            )}

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
                                            to={`https://github.com/PostHog/posthog/issues/new?&labels=enhancement&template=feature_request.yml&debug-info=${encodeURIComponent(
                                                getPublicSupportSnippet(region, currentOrganization, currentTeam)
                                            )}`}
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
        </>
    )
}
