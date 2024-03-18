import {
    IconBug,
    IconChevronDown,
    IconFeatures,
    IconFlask,
    IconHelmet,
    IconMap,
    IconMessage,
    IconRewindPlay,
    IconStack,
    IconToggle,
    IconTrends,
} from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SupportForm } from 'lib/components/Support/SupportForm'
import { supportLogic } from 'lib/components/Support/supportLogic'
import React from 'react'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, ProductKey, SidePanelTab } from '~/types'

import AlgoliaSearch from '../../components/AlgoliaSearch'
import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { SIDE_PANEL_TABS } from '../SidePanel'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

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
        slug: 'ab-testing',
        icon: <IconFlask className="text-purple h-5 w-5" />,
    },
    {
        name: 'Surveys',
        slug: 'surveys',
        icon: <IconMessage className="text-danger h-5 w-5" />,
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
    const { billing } = useValues(billingLogic)
    const supportResponseTimes = {
        [AvailableFeature.EMAIL_SUPPORT]: '2-3 days',
        [AvailableFeature.PRIORITY_SUPPORT]: '4-6 hours',
    }

    return (
        <Section title="Email an engineer">
            <div className="grid grid-cols-2 border rounded [&_>*]:px-2 [&_>*]:py-0.5 mb-4 bg-bg-light">
                <div className="col-span-full flex justify-between border-b bg-bg-white py-1">
                    <div>
                        <strong>Avg support response times</strong>
                    </div>
                    <div>
                        <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>Explore options</Link>
                    </div>
                </div>
                {billing?.products
                    ?.find((product) => product.type == ProductKey.PLATFORM_AND_SUPPORT)
                    ?.plans?.map((plan, i) => (
                        <React.Fragment key={`support-panel-${plan.plan_key}`}>
                            <div className={plan.current_plan ? 'font-bold' : undefined}>
                                {i == 1 ? 'Pay-per-use' : plan.name}
                                {plan.current_plan && (
                                    <>
                                        {' '}
                                        <span className="font-normal opacity-60 text-sm">(your plan)</span>
                                    </>
                                )}
                            </div>
                            <div className={plan.current_plan ? 'font-bold' : undefined}>
                                {plan.features.some((f) => f.key == AvailableFeature.PRIORITY_SUPPORT)
                                    ? supportResponseTimes[AvailableFeature.PRIORITY_SUPPORT]
                                    : plan.features.some((f) => f.key == AvailableFeature.EMAIL_SUPPORT)
                                    ? supportResponseTimes[AvailableFeature.EMAIL_SUPPORT]
                                    : 'Community support only'}
                            </div>
                        </React.Fragment>
                    ))}
            </div>
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
        </Section>
    )
}

export const SidePanelSupport = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const { openEmailForm, closeEmailForm } = useActions(supportLogic)
    const { isEmailFormOpen } = useValues(supportLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { title } = useValues(theLogic)

    return (
        <>
            <SidePanelPaneHeader title={isEmailFormOpen ? title : SIDE_PANEL_TABS[SidePanelTab.Support].label} />

            <div className="overflow-y-auto" data-attr="side-panel-support-container">
                <div className="p-3 max-w-160 w-full mx-auto">
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
                                            <span className="text-default opacity-75 group-hover:opacity-100">
                                                {product.name}
                                            </span>
                                        </div>
                                        <div>
                                            <IconChevronDown className="text-default h-6 w-6 opacity-60 -rotate-90 group-hover:opacity-90" />
                                        </div>
                                    </Link>
                                </li>
                            ))}
                        </ul>
                    </Section>

                    <Section title="Ask the community">
                        <p>
                            Questions about features, how to's, or use cases? There are thousands of discussions in our
                            community forums.
                        </p>
                        <LemonButton
                            type="primary"
                            fullWidth
                            center
                            to="https://posthog.com/questions"
                            targetBlank
                            className="mt-2"
                        >
                            Ask a question
                        </LemonButton>
                    </Section>

                    <Section title="Share feedback">
                        <ul>
                            <li>
                                <LemonButton
                                    type="secondary"
                                    status="alt"
                                    to="https://github.com/posthog/posthog/issues"
                                    icon={<IconBug />}
                                    targetBlank
                                >
                                    Report a bug
                                </LemonButton>
                            </li>
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
                                    to="https://github.com/posthog/posthog/issues"
                                    icon={<IconFeatures />}
                                    targetBlank
                                >
                                    Request a feature
                                </LemonButton>
                            </li>
                        </ul>
                    </Section>

                    {hasAvailableFeature(AvailableFeature.EMAIL_SUPPORT) ? (
                        <Section title="More options">
                            {isEmailFormOpen ? (
                                <SupportFormBlock onCancel={() => closeEmailForm()} />
                            ) : (
                                <p>
                                    Can't find what you need in the docs?{' '}
                                    <Link onClick={() => openEmailForm()}>Email an engineer</Link>
                                </p>
                            )}
                        </Section>
                    ) : (
                        <Section title="Contact support">
                            <p>
                                Due to our large userbase, we're unable to offer email support to organizations on the
                                free plan. But we still want to help!
                            </p>

                            <ol className="pl-5">
                                <li>
                                    <strong className="block">Search our docs</strong>
                                    <p>
                                        We're constantly updating our docs and tutorials to provide the latest
                                        information about installing, using, and troubleshooting.
                                    </p>
                                </li>
                                <li>
                                    <strong className="block">Ask a community question</strong>
                                    <p>
                                        Many common (and niche) questions have already been resolved by users just like
                                        you. (Our own engineers also keep an eye on the questions as they have time!){' '}
                                        <Link to="https://posthog.com/question" className="block">
                                            Search community questions or ask your own.
                                        </Link>
                                    </p>
                                </li>
                                <li>
                                    <strong className="block">
                                        Explore <Link to="https://posthog.com/partners">PostHog partners</Link>
                                    </strong>
                                    <p>
                                        Third-party providers can help with installation and debugging of data issues.
                                    </p>
                                </li>
                                <li>
                                    <strong className="block">Upgrade to a paid plan</strong>
                                    <p>
                                        Our paid plans offer email support.{' '}
                                        <Link to={urls.organizationBilling([ProductKey.PLATFORM_AND_SUPPORT])}>
                                            Explore options.
                                        </Link>
                                    </p>
                                </li>
                            </ol>
                        </Section>
                    )}
                </div>
            </div>
        </>
    )
}
