import {
    IconAI,
    IconBook,
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
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, BillingFeatureType, BillingType, ProductKey } from '~/types'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'

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
            <>
                <h3>{title}</h3>
                {children}
            </>
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

                    {/* Show response time information from billing plans */}
                    <SupportResponseTimesTable billing={billing} hasActiveTrial={hasActiveTrial} isCompact={true} />
                </>
            )}
        </Section>
    )
}

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
    const teamsAddonActive = !!hasTeamsAddon || hasTeamsAddonAlt

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
    const plansToDisplay = [
        {
            name: 'Totally free',
            current_plan: billing?.subscription_level === 'free' && !hasActiveTrial && !hasEnterprisePlan,
            features: [{ note: 'Community support only' }],
            plan_key: 'free',
            link: 'https://posthog.com/questions',
        },
        {
            name: 'Teams add-on',
            current_plan: teamsAddonActive,
            features: [
                getResponseTimeFeature('Teams add-on') || {
                    note: '4 business hours',
                },
            ],
            plan_key: 'teams',
        },
        {
            name: 'Enterprise plan',
            current_plan: hasEnterprisePlan,
            features: [
                getResponseTimeFeature('Enterprise plan') || {
                    note: '2 business hours',
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
                    <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>Explore options</Link>
                </div>
            </div>

            {plansToDisplay.map((plan) => {
                const isBold = plan.current_plan

                const responseNote = plan.features.find(
                    (f) => (f as any).key === AvailableFeature.SUPPORT_RESPONSE_TIME || (f as any).note
                )?.note

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
                                {isBold && <span className="text-muted text-xs font-normal">(current)</span>}
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

            {hasExpiredTrial && expiredTrialDate && (
                <div className="border-t col-span-2 text-muted pt-1 text-xs italic" data-attr="support-trial-note">
                    Your Teams add-on trial expired on{' '}
                    {expiredTrialDate.format(isCompact ? 'D MMM YYYY' : 'D MMMM YYYY')}.
                </div>
            )}
        </div>
    )
}

export function SidePanelSupport(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const {
        isEmailFormOpen,
        title: supportPanelTitle,
    } = useValues(supportLogic)
    const { closeEmailForm, openEmailForm, closeSupportForm } = useActions(supportLogic)
    const { billing } = useValues(billingLogic)

    const cloudOrSelfHosted = preflight?.cloud ? 'Cloud' : preflight?.demo ? 'Demo' : 'Self-hosted'
    const userEmail = user?.email || ''

    // Check for support access
    const canEmail = billing?.subscription_level !== 'free' || (!!billing?.trial?.status && billing.trial.status === 'active')

    // Check if we're on a paid plan or active trial
    const hasActiveTrial = !!billing?.trial?.status && billing.trial.status === 'active'

    const handleOpenEmailForm = (): void => {
        openEmailForm()
    }

    return (
        <div className="SidePanelSupport">
            <SidePanelPaneHeader
                title={isEmailFormOpen ? supportPanelTitle : 'Help'}
            />

            <div className="px-6 py-2 space-y-6">
                {isEmailFormOpen ? (
                    <SupportFormBlock
                        onCancel={() => {
                            closeEmailForm()
                            closeSupportForm()
                        }}
                        hasActiveTrial={hasActiveTrial}
                        billing={billing}
                    />
                ) : (
                    <>
                        <Section title="Email an engineer">
                            <p>
                                Reach out to a PostHog engineer directly if you need help.
                                <br />
                                We respond based on your support plan.
                            </p>
                            {canEmail ? (
                                <LemonButton
                                    onClick={handleOpenEmailForm}
                                    type="primary"
                                    fullWidth
                                    center
                                    className="mt-2"
                                >
                                    Email an engineer
                                </LemonButton>
                            ) : (
                                <>
                                    <SupportResponseTimesTable
                                        billing={billing}
                                        hasActiveTrial={hasActiveTrial}
                                        isCompact={false}
                                    />

                                    <LemonBanner type="info">
                                        <div className="mb-2">
                                            <strong>Need email support?</strong>
                                        </div>
                                        <p className="mb-2">
                                            Email support is available on paid plans, or with the Teams add-on.
                                        </p>
                                        <LemonButton
                                            to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}
                                            type="secondary"
                                            fullWidth
                                            center
                                        >
                                            Explore options
                                        </LemonButton>
                                    </LemonBanner>
                                </>
                            )}
                        </Section>

                        <Section title="Access support info">
                            <div className="flex gap-1 flex-col">
                                <div className="font-semibold mb-1">Current version</div>
                                <div>{(preflight as any)?.posthog_version || ''}</div>
                            </div>
                            <div className="flex gap-1 flex-col pt-4">
                                <div className="font-semibold mb-1">Deployment type</div>
                                <div>{cloudOrSelfHosted}</div>
                            </div>
                            <div className="flex gap-1 flex-col pt-4">
                                <div className="font-semibold mb-1">Your organization</div>
                                <div>{currentOrganization?.name}</div>
                            </div>
                            <div className="flex gap-1 flex-col pt-4">
                                <div className="font-semibold mb-1">Your project</div>
                                <div>{currentTeam?.name}</div>
                            </div>
                            <div className="flex gap-1 flex-col pt-4">
                                <div className="font-semibold mb-1">Your email</div>
                                <div>{userEmail}</div>
                            </div>
                            {preflight?.cloud && (
                                <div className="pt-4">
                                    <div className="font-semibold mb-1">Snippet for support team</div>
                                    <textarea
                                        readOnly
                                        className="SidePanelSupport__FormBlockTextarea h-20 font-mono text-xs"
                                        value={getPublicSupportSnippet(
                                            preflight?.region,
                                            currentOrganization,
                                            currentTeam
                                        )}
                                    />
                                </div>
                            )}
                        </Section>

                        <Section title="Visit PostHog docs">
                            <LemonButton
                                fullWidth
                                center
                                sideIcon={<IconHelmet />}
                                to="https://posthog.com/docs"
                                targetBlank
                            >
                                Documentation
                            </LemonButton>
                        </Section>

                        <Section title="Key features">
                            <div className="grid grid-cols-2 gap-1">
                                <LemonButton
                                    to="https://posthog.com/docs/data"
                                    targetBlank
                                    fullWidth
                                    center
                                    className="flex-col h-20 p-2"
                                >
                                    <IconMap className="text-xl mb-1" />
                                    <div className="font-medium">Data</div>
                                </LemonButton>
                                <LemonButton
                                    to="https://posthog.com/docs/feature-flags"
                                    targetBlank
                                    fullWidth
                                    center
                                    className="flex-col h-20 p-2"
                                >
                                    <IconFeatures className="text-xl mb-1" />
                                    <div className="font-medium">Feature flags</div>
                                </LemonButton>
                            </div>
                        </Section>

                        <Section title="All products">
                            <LemonCollapse
                                panels={[
                                    {
                                        key: 'all-products',
                                        header: 'View all products',
                                        content: (
                                            <div className="grid grid-cols-2 gap-1">
                                                {PRODUCTS.map((product) => (
                                                    <LemonButton
                                                        key={product.slug}
                                                        to={`https://posthog.com/docs/products/${product.slug}`}
                                                        targetBlank
                                                        fullWidth
                                                        center
                                                        className="flex-col h-20 p-2"
                                                    >
                                                        <div className="mb-1">{product.icon}</div>
                                                        <div className="font-medium text-center text-sm">
                                                            {product.name}
                                                        </div>
                                                    </LemonButton>
                                                ))}
                                            </div>
                                        ),
                                    },
                                ]}
                            />
                        </Section>

                        <Section title="Still need help?">
                            <div className="flex flex-col gap-1">
                                <LemonButton
                                    to="https://posthog.com/questions"
                                    targetBlank
                                    fullWidth
                                    center
                                    sideIcon={<IconMessage className="mr-1" />}
                                >
                                    Community forum
                                </LemonButton>

                                <LemonButton
                                    to="https://posthog.com/docs"
                                    targetBlank
                                    fullWidth
                                    center
                                    sideIcon={<IconBook className="mr-1" />}
                                >
                                    Documentation
                                </LemonButton>
                            </div>
                        </Section>
                    </>
                )}
            </div>
        </div>
    )
}
