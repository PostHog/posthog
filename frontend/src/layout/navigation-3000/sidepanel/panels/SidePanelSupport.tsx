import {
    IconAI,
    IconChevronDown,
    IconDatabase,
    IconDecisionTree,
    IconFeatures,
    IconFlask,
    IconHelmet,
    IconMap,
    IconMessage,
    IconPieChart,
    IconRewindPlay,
    IconStack,
    IconToggle,
    IconTrends,
} from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SupportForm } from 'lib/components/Support/SupportForm'
import { getPublicSupportSnippet, supportLogic } from 'lib/components/Support/supportLogic'
import React from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AvailableFeature, ProductKey, SidePanelTab } from '~/types'

import AlgoliaSearch from '../../components/AlgoliaSearch'
import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { SIDE_PANEL_TABS } from '../SidePanel'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
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
        icon: <IconTrends className="text-brand-blue h-5 w-5" />,
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
        icon: <IconToggle className="text-success h-5 w-5" />,
    },
    {
        name: 'A/B testing',
        slug: 'experiments',
        icon: <IconFlask className="text-purple h-5 w-5" />,
    },
    {
        name: 'Surveys',
        slug: 'surveys',
        icon: <IconMessage className="text-danger h-5 w-5" />,
    },
    {
        name: 'Data pipelines',
        slug: 'cdp',
        icon: <IconDecisionTree className="text-[#2EA2D3] h-5 w-5" />,
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
            <h3>{title}</h3>
            {children}
        </section>
    )
}

const SupportFormBlock = ({ onCancel }: { onCancel: () => void }): JSX.Element => {
    const { supportPlans, hasSupportAddonPlan } = useValues(billingLogic)

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
                className="mt-2"
            >
                Cancel
            </LemonButton>
            <div className="grid grid-cols-2 border rounded [&_>*]:px-2 [&_>*]:py-0.5 mb-4 bg-bg-light">
                <div className="col-span-full flex justify-between border-b bg-bg-white py-1">
                    <div>
                        <strong>Avg support response times</strong>
                    </div>
                    <div>
                        <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>Explore options</Link>
                    </div>
                </div>
                {supportPlans?.map((plan) => {
                    // If they have an addon plan, only show the addon plan
                    const currentPlan = plan.current_plan && (!hasSupportAddonPlan || plan.plan_key?.includes('addon'))
                    return (
                        <React.Fragment key={`support-panel-${plan.plan_key}`}>
                            <div className={currentPlan ? 'font-bold' : undefined}>
                                {plan.name}
                                {currentPlan && (
                                    <>
                                        {' '}
                                        <span className="font-normal opacity-60 text-sm">(your plan)</span>
                                    </>
                                )}
                            </div>
                            <div className={currentPlan ? 'font-bold' : undefined}>
                                {/* TODO(@zach): remove fallback after updated plans w/ support levels are shipped */}
                                {plan.features.find((f) => f.key == AvailableFeature.SUPPORT_RESPONSE_TIME)?.note}
                            </div>
                        </React.Fragment>
                    )
                })}
            </div>
        </Section>
    )
}

export const SidePanelSupport = (): JSX.Element => {
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { preflight, isCloud } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const { status } = useValues(sidePanelStatusLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { openEmailForm, closeEmailForm } = useActions(theLogic)
    const { title, isEmailFormOpen } = useValues(theLogic)

    const region = preflight?.region

    return (
        <>
            <SidePanelPaneHeader title={isEmailFormOpen ? title : SIDE_PANEL_TABS[SidePanelTab.Support].label} />

            <div className="overflow-y-auto" data-attr="side-panel-support-container">
                <div className="p-3 max-w-160 w-full mx-auto">
                    {isEmailFormOpen ? (
                        <SupportFormBlock onCancel={() => closeEmailForm()} />
                    ) : (
                        <>
                            <Section title="Search docs & community questions">
                                <AlgoliaSearch />
                            </Section>

                            <Section title="Explore the docs">
                                <ul className="border rounded divide-y bg-bg-light dark:bg-transparent font-title font-medium">
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

                            {status !== 'operational' ? (
                                <Section title="">
                                    <LemonBanner type={status.includes('outage') ? 'error' : 'warning'}>
                                        <div>
                                            <span>
                                                We are experiencing {status.includes('outage') ? 'major' : ''} issues.
                                            </span>
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
                            ) : null}

                            {/* only allow opening tickets on our Cloud instances */}
                            {isCloud ? (
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
                                        Email an engineer
                                    </LemonButton>
                                </Section>
                            ) : null}
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
