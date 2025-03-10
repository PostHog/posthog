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
    const { supportPlans, hasSupportAddonPlan } = useValues(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const supportPlansToDisplay = supportPlans?.filter((plan) => plan.name !== 'Enterprise add-on')

    // Plan detection logic
    const hasTeamsAddon = billing?.products?.some((p) => p.type === 'teams')

    // Alternative detection method
    const hasTeamsAddonAlt = supportPlans?.some((plan) => plan.name === 'Teams add-on' && plan.current_plan === true)

    // Combine both detection methods
    const teamsAddonActive = hasTeamsAddon || hasTeamsAddonAlt

    // Check for enterprise plan
    const hasEnterprisePlan = billing?.products?.some((p) => p.type === 'enterprise')

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

    /* Commenting out debug info object for clean screenshots
    const debugInfo: {
        supportPlansExist: boolean;
        supportPlansLength: number;
        supportPlansToDisplayExist: boolean;
        supportPlansToDisplayLength: number;
        hasSupportAddonPlan: boolean;
        hasTeamsAddon: boolean | undefined;
        hasTeamsAddonAlt: boolean | undefined;
        teamsAddonActive: boolean | undefined;
        hasEnterprisePlan: boolean | undefined;
        hasExpiredTrial: boolean;
        subscriptionLevel: string | undefined;
        productsCount: number;
        productsTypes: string;
        billingSubscription: string;
    } = {
        supportPlansExist: !!supportPlans,
        supportPlansLength: supportPlans?.length || 0,
        supportPlansToDisplayExist: !!supportPlansToDisplay,
        supportPlansToDisplayLength: supportPlansToDisplay?.length || 0,
        hasSupportAddonPlan,
        hasTeamsAddon,
        hasTeamsAddonAlt,
        teamsAddonActive,
        hasEnterprisePlan,
        hasExpiredTrial,
        subscriptionLevel: billing?.subscription_level,
        productsCount: billing?.products?.length || 0,
        productsTypes: billing?.products?.map(p => p.type).join(', ') || 'none',
        billingSubscription: billing?.has_active_subscription ? 'yes' : 'no'
    };
    */

    // Remove console.log to fix linter error, we'll use UI debug instead
    // console.log('SupportFormBlock Debug:', debugInfo);

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
                        <strong>Support hours, Monday - Friday:</strong>
                        <div className="text-xs mt-1">
                            <div>Winter: UTC 08:00 - UTC 01:00 (next day)</div>
                            <div>Summer: UTC 07:00 - UTC 00:00 (midnight)</div>
                        </div>
                    </div>

                    {/* Table shown below email support form */}
                    <div className="grid grid-cols-2 border rounded [&_>*]:px-2 [&_>*]:py-0.5 mb-4 bg-surface-primary pt-4">
                        <div className="col-span-full flex justify-between py-1">
                            {/* If placing a support message, replace the line below with explanation */}
                            <strong>Avg support response times</strong>
                            <div>
                                <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>
                                    Explore options
                                </Link>
                            </div>
                        </div>

                        {/* Table content - plans and trial info together */}
                        {supportPlansToDisplay ? (
                            /* Dynamic version using billing data */
                            <>
                                {supportPlansToDisplay.map((plan) => {
                                    // Check if Teams add-on is active - moved to component level
                                    // Use component-level teamsAddonActive variable rather than redefining

                                    // Don't show Ridiculously cheap as current plan when Teams add-on or Enterprise is active
                                    const isCurrentPlan =
                                        plan.current_plan &&
                                        (!hasSupportAddonPlan || plan.plan_key?.includes('addon')) &&
                                        (!hasActiveTrial || plan.name !== 'Totally free') &&
                                        !(billing?.subscription_level === 'paid' && plan.name === 'Totally free') &&
                                        !(teamsAddonActive && plan.name === 'Ridiculously cheap') &&
                                        !(hasEnterprisePlan && plan.name === 'Ridiculously cheap')

                                    // For Teams add-on, force it to be the current plan when it's active
                                    const isTeamsAddonActive = teamsAddonActive && plan.name === 'Teams add-on'

                                    // For Enterprise, force it to be the current plan when it's active
                                    const isEnterprisePlanActive = hasEnterprisePlan && plan.name === 'Enterprise'

                                    // Check if Ridiculously cheap should show as current plan
                                    const isRidiculouslyCheapCurrentPlan =
                                        billing?.subscription_level === 'paid' &&
                                        plan.name === 'Ridiculously cheap' &&
                                        !teamsAddonActive &&
                                        !hasEnterprisePlan

                                    const responseNote = plan.features.find(
                                        (f: { key: any }) => f.key == AvailableFeature.SUPPORT_RESPONSE_TIME
                                    )?.note

                                    return (
                                        <React.Fragment key={`support-panel-${plan.plan_key}`}>
                                            <div
                                                className={
                                                    isCurrentPlan ||
                                                    isTeamsAddonActive ||
                                                    isEnterprisePlanActive ||
                                                    isRidiculouslyCheapCurrentPlan
                                                        ? 'font-bold'
                                                        : undefined
                                                }
                                            >
                                                {plan.name}
                                                {/* Show (your plan) based on the following prioritized rules:
                                                1. For Teams add-on: Show if it's active
                                                2. For Enterprise: Show if it's active
                                                3. For other plans: Show if it's the current plan (except Totally free)
                                                4. For Ridiculously cheap: Show ONLY if it's paid AND neither Teams add-on nor Enterprise is active */}
                                                {(isTeamsAddonActive ||
                                                    isEnterprisePlanActive ||
                                                    (isCurrentPlan && plan.name !== 'Totally free') ||
                                                    isRidiculouslyCheapCurrentPlan) &&
                                                    !(teamsAddonActive && plan.name === 'Ridiculously cheap') &&
                                                    !(hasEnterprisePlan && plan.name === 'Ridiculously cheap') && (
                                                        <>
                                                            {' '}
                                                            <span className="font-normal opacity-60 text-sm">
                                                                (your plan)
                                                            </span>
                                                        </>
                                                    )}
                                            </div>
                                            <div
                                                className={
                                                    isCurrentPlan ||
                                                    isTeamsAddonActive ||
                                                    isEnterprisePlanActive ||
                                                    isRidiculouslyCheapCurrentPlan
                                                        ? 'font-bold'
                                                        : undefined
                                                }
                                            >
                                                {responseNote
                                                    ? responseNote === '24 hours'
                                                        ? '24 business hours'
                                                        : responseNote === '12 hours'
                                                        ? '12 business hours'
                                                        : responseNote
                                                    : 'Community support only'}
                                            </div>
                                        </React.Fragment>
                                    )
                                })}

                                {/* Display trial information integrated into the table */}
                                {hasActiveTrial && (
                                    <>
                                        <div className={hasActiveTrial ? 'font-bold border-t' : 'border-t'}>
                                            Your trial
                                        </div>
                                        <div className={hasActiveTrial ? 'font-bold border-t' : 'border-t'}>
                                            24 business hours
                                        </div>
                                        {/* Show expiration date for both old-style and new-style trials */}
                                        {billing?.free_trial_until && (
                                            <div className="col-span-2 text-sm">
                                                (trial expires {billing.free_trial_until.format('MMMM D, YYYY')})
                                            </div>
                                        )}
                                        {billing?.trial?.expires_at && !billing?.free_trial_until && (
                                            <div className="col-span-2 text-sm">
                                                (trial expires {dayjs(billing.trial.expires_at).format('MMMM D, YYYY')})
                                            </div>
                                        )}
                                    </>
                                )}

                                {/* Display expired trial information */}
                                {!hasActiveTrial && hasExpiredTrial && expiredTrialDate && (
                                    <>
                                        <div className="border-t text-muted">Trial expired</div>
                                        <div className="border-t text-muted">
                                            {expiredTrialDate.format('MMMM D, YYYY')}
                                        </div>
                                    </>
                                )}
                            </>
                        ) : (
                            // Static version used when dynamic data isn't available
                            <>
                                <div>
                                    Totally free
                                    {billing?.subscription_level === 'free' && !hasActiveTrial && (
                                        <span className="ml-1 text-sm opacity-60">(your plan)</span>
                                    )}
                                </div>
                                <div>Community support only</div>
                                <div>
                                    Ridiculously cheap
                                    {/* Use combined detection method */}
                                    {billing?.subscription_level === 'paid' &&
                                        !teamsAddonActive &&
                                        !hasEnterprisePlan && (
                                            <span className="ml-1 text-sm opacity-60">(your plan)</span>
                                        )}
                                </div>
                                <div
                                    className={
                                        billing?.subscription_level === 'paid' &&
                                        !teamsAddonActive &&
                                        !hasEnterprisePlan
                                            ? 'font-bold'
                                            : ''
                                    }
                                >
                                    24 business hours
                                </div>
                                <div>
                                    Teams add-on
                                    {teamsAddonActive && <span className="ml-1 text-sm opacity-60">(your plan)</span>}
                                </div>
                                <div className={teamsAddonActive ? 'font-bold' : ''}>12 business hours</div>
                                <div>
                                    Enterprise
                                    {hasEnterprisePlan && <span className="ml-1 text-sm opacity-60">(your plan)</span>}
                                </div>
                                <div className={hasEnterprisePlan ? 'font-bold' : ''}>12 business hours</div>

                                {/* Display trial information in static template as well */}
                                {hasActiveTrial && (
                                    <>
                                        <div className={hasActiveTrial ? 'font-bold border-t' : 'border-t'}>
                                            Your trial
                                        </div>
                                        <div className={hasActiveTrial ? 'font-bold border-t' : 'border-t'}>
                                            24 business hours
                                        </div>
                                        {/* Show expiration date for both old-style and new-style trials */}
                                        {billing?.free_trial_until && (
                                            <div className="col-span-2 text-sm">
                                                (trial expires {billing.free_trial_until.format('MMMM D, YYYY')})
                                            </div>
                                        )}
                                        {billing?.trial?.expires_at && !billing?.free_trial_until && (
                                            <div className="col-span-2 text-sm">
                                                (trial expires {dayjs(billing.trial.expires_at).format('MMMM D, YYYY')})
                                            </div>
                                        )}
                                    </>
                                )}

                                {/* Display expired trial information */}
                                {!hasActiveTrial && hasExpiredTrial && expiredTrialDate && (
                                    <>
                                        <div className="border-t text-muted">Trial expired</div>
                                        <div className="border-t text-muted">
                                            {expiredTrialDate.format('MMMM D, YYYY')}
                                        </div>
                                    </>
                                )}
                            </>
                        )}
                    </div>
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
    supportPlansToDisplay?: any[] // Use the correct type from billingLogic
    isCompact?: boolean
}): JSX.Element => {
    const { supportPlans } = useValues(billingLogic)

    // Check if Teams add-on is active using both methods
    const hasTeamsAddon = billing?.products?.some((p) => p.type === 'teams')
    const hasTeamsAddonAlt = supportPlans?.some((plan) => plan.name === 'Teams add-on' && plan.current_plan === true)
    const teamsAddonActive = hasTeamsAddon || hasTeamsAddonAlt

    // Check for enterprise plan
    const hasEnterprisePlan = billing?.products?.some((p) => p.type === 'enterprise')

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
                {/* If placing a support message, replace the line below with explanation */}
                <strong>Avg support response times</strong>
                <div>
                    <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>Explore options</Link>
                </div>
            </div>

            {supportPlansToDisplay ? (
                // Used by SupportFormBlock
                <>
                    {supportPlansToDisplay.map((plan) => {
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
                        const isEnterprisePlanActive = hasEnterprisePlan && plan.name === 'Enterprise'

                        // Check if Ridiculously cheap should show as current plan
                        const isRidiculouslyCheapCurrentPlan =
                            billing?.subscription_level === 'paid' &&
                            plan.name === 'Ridiculously cheap' &&
                            !teamsAddonActive &&
                            !hasEnterprisePlan

                        const responseNote = plan.features.find(
                            (f: { key: any }) => f.key == AvailableFeature.SUPPORT_RESPONSE_TIME
                        )?.note

                        return (
                            <React.Fragment key={`support-panel-${plan.plan_key}`}>
                                <div
                                    className={
                                        isCurrentPlan ||
                                        isTeamsAddonActive ||
                                        isEnterprisePlanActive ||
                                        isRidiculouslyCheapCurrentPlan
                                            ? 'font-bold'
                                            : undefined
                                    }
                                >
                                    {plan.name}
                                    {/* Show (your plan) label for: 
                                    1. Teams add-on when active, OR
                                    2. Enterprise when active, OR
                                    3. Current plan (excluding Totally free), OR
                                    4. Ridiculously cheap ONLY when neither Teams add-on nor Enterprise is active */}
                                    {(isTeamsAddonActive ||
                                        isEnterprisePlanActive ||
                                        (isCurrentPlan && plan.name !== 'Totally free') ||
                                        isRidiculouslyCheapCurrentPlan) &&
                                        !(teamsAddonActive && plan.name === 'Ridiculously cheap') &&
                                        !(hasEnterprisePlan && plan.name === 'Ridiculously cheap') && (
                                            <>
                                                {' '}
                                                <span className="font-normal opacity-60 text-sm">(your plan)</span>
                                            </>
                                        )}
                                </div>
                                <div
                                    className={
                                        isCurrentPlan ||
                                        isTeamsAddonActive ||
                                        isEnterprisePlanActive ||
                                        isRidiculouslyCheapCurrentPlan
                                            ? 'font-bold'
                                            : undefined
                                    }
                                >
                                    {responseNote
                                        ? responseNote === '24 hours'
                                            ? '24 business hours'
                                            : responseNote === '12 hours'
                                            ? '12 business hours'
                                            : responseNote
                                        : 'Community support only'}
                                </div>
                            </React.Fragment>
                        )
                    })}

                    {/* Display trial information integrated into the table */}
                    {hasActiveTrial && (
                        <>
                            <div className={hasActiveTrial ? 'font-bold border-t' : 'border-t'}>Your trial</div>
                            <div className={hasActiveTrial ? 'font-bold border-t' : 'border-t'}>24 business hours</div>
                            {/* Show expiration date for both old-style and new-style trials */}
                            {billing?.free_trial_until && (
                                <div className="col-span-2 text-sm">
                                    (trial expires {billing.free_trial_until.format('MMMM D, YYYY')})
                                </div>
                            )}
                            {billing?.trial?.expires_at && !billing?.free_trial_until && (
                                <div className="col-span-2 text-sm">
                                    (trial expires {dayjs(billing.trial.expires_at).format('MMMM D, YYYY')})
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
                </>
            ) : (
                // Static version used when !showEmailSupport
                <>
                    <div>
                        Totally free
                        {billing?.subscription_level === 'free' && !hasActiveTrial && (
                            <span className="ml-1 text-sm opacity-60">(your plan)</span>
                        )}
                    </div>
                    <div>
                        <Link to="https://posthog.com/questions">Community support only</Link>
                    </div>
                    <div>
                        Ridiculously cheap
                        {/* Use combined detection method */}
                        {billing?.subscription_level === 'paid' && !teamsAddonActive && !hasEnterprisePlan && (
                            <span className="ml-1 text-sm opacity-60">(your plan)</span>
                        )}
                    </div>
                    <div
                        className={
                            billing?.subscription_level === 'paid' && !teamsAddonActive && !hasEnterprisePlan
                                ? 'font-bold'
                                : ''
                        }
                    >
                        24 business hours
                    </div>
                    <div>
                        Teams add-on
                        {teamsAddonActive && <span className="ml-1 text-sm opacity-60">(your plan)</span>}
                    </div>
                    <div className={teamsAddonActive ? 'font-bold' : ''}>12 business hours</div>
                    <div>
                        Enterprise
                        {hasEnterprisePlan && <span className="ml-1 text-sm opacity-60">(your plan)</span>}
                    </div>
                    <div className={hasEnterprisePlan ? 'font-bold' : ''}>12 business hours</div>

                    {/* Display trial information integrated into the table */}
                    {hasActiveTrial && (
                        <>
                            <div className={hasActiveTrial ? 'font-bold border-t' : 'border-t'}>Your trial</div>
                            <div className={hasActiveTrial ? 'font-bold border-t' : 'border-t'}>24 business hours</div>
                            {/* Show expiration date for both old-style and new-style trials */}
                            {billing?.free_trial_until && (
                                <div className="col-span-2 text-sm">
                                    (trial expires {billing.free_trial_until.format('MMMM D, YYYY')})
                                </div>
                            )}
                            {billing?.trial?.expires_at && !billing?.free_trial_until && (
                                <div className="col-span-2 text-sm">
                                    (trial expires {dayjs(billing.trial.expires_at).format('MMMM D, YYYY')})
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
    const { billing } = useValues(billingLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { openEmailForm, closeEmailForm, openMaxChatInterface, closeMaxChatInterface } = useActions(theLogic)
    const { isEmailFormOpen, isMaxChatInterfaceOpen } = useValues(theLogic)

    const region = preflight?.region

    const isLocalDev = process.env.NODE_ENV === 'development'

    // Check if user has a paid subscription or is on an active trial
    const hasActiveTrial =
        (!!billing?.free_trial_until && billing.free_trial_until.isAfter(dayjs())) ||
        billing?.trial?.status === 'active'

    const canEmailEngineer = billing?.subscription_level !== 'free' || hasActiveTrial
    // In development, we always show the button regardless of cloud status
    const showEmailSupport = isLocalDev ? canEmailEngineer : preflight?.cloud && canEmailEngineer

    return (
        <>
            <div className="overflow-y-auto" data-attr="side-panel-support-container">
                <SidePanelPaneHeader title="Help" />
                <div className="p-3 max-w-160 w-full mx-auto">
                    {/* Debug panel removed for clean code */}

                    {isEmailFormOpen ? (
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

                            {!showEmailSupport && (
                                <Section title="">
                                    <h3>Can't find what you need in the docs?</h3>
                                    <p>
                                        With the totally free plan you can ask the community via the link below, or
                                        explore your upgrade choices for the ability to email a support engineer.
                                    </p>
                                </Section>
                            )}

                            {showEmailSupport && (
                                <Section title="Contact us">
                                    <p>Can't find what you need in the docs?</p>
                                    <LemonButton
                                        type="primary"
                                        fullWidth
                                        center
                                        onClick={() => openEmailForm()}
                                        targetBlank
                                        className="mt-2"
                                    >
                                        Email our support engineers
                                    </LemonButton>
                                </Section>
                            )}

                            {!showEmailSupport && (
                                <>
                                    <SupportResponseTimesTable
                                        billing={billing}
                                        hasActiveTrial={hasActiveTrial}
                                        supportPlansToDisplay={undefined}
                                    />
                                </>
                            )}

                            <Section title="Ask the community">
                                <p>
                                    Questions about features, how-tos, or use cases? There are thousands of discussions
                                    in our community forums.{' '}
                                    <Link to="https://posthog.com/questions">Ask a question</Link>
                                </p>
                            </Section>

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
