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

import { SidePanelTab } from '~/types'

import AlgoliaSearch from '../../components/AlgoliaSearch'
import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

export const SidePanelSupport = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    const theLogic = supportLogic({ onClose: () => closeSidePanel(SidePanelTab.Support) })
    const { title } = useValues(theLogic)
    const { closeSupportForm } = useActions(theLogic)

    const Section = ({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement => {
        return (
            <section className="mb-6">
                <h3>{title}</h3>
                {children}
            </section>
        )
    }

    const products = [
        {
            name: 'Product OS',
            slug: 'product-os',
            icon: <IconStack className="text-red h-5 w-5" />,
        },
        {
            name: 'Product analytics',
            slug: 'product-analytics',
            icon: <IconTrends className="text-blue h-5 w-5" />,
        },
        {
            name: 'Session replay',
            slug: 'session-replay',
            icon: <IconRewindPlay className="text-yellow h-5 w-5" />,
        },
        {
            name: 'Feature flags',
            slug: 'feature-flags',
            icon: <IconToggle className="text-green h-5 w-5" />,
        },
        {
            name: 'A/B testing',
            slug: 'ab-testing',
            icon: <IconFlask className="text-purple h-5 w-5" />,
        },
        {
            name: 'Surveys',
            slug: 'surveys',
            icon: <IconMessage className="text-red h-5 w-5" />,
        },
    ]

    return (
        <>
            <SidePanelPaneHeader title={title} />

            <div className="overflow-y-auto" data-attr="side-panel-support-container">
                <div className="p-3 max-w-160 w-full mx-auto">
                    <Section title="Search docs & community questions">
                        <AlgoliaSearch />
                    </Section>

                    <Section title="Explore the docs">
                        <ul className="border rounded divide-y bg-bg-light dark:bg-transparent font-title font-medium">
                            {products.map((product, index) => (
                                <li key={index}>
                                    <Link
                                        to={`/docs/${product.slug}`}
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
                            Questions about features, how to's, or use cases? There are <strong>1,634</strong>{' '}
                            discussions in our community forums.
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
                                    to="https://posthog.com/roadmap"
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

                    {/* 
                        sections below are conditional, depending on which type of support they're supposed to get.
                        See types.tsx: https://github.com/PostHog/posthog/pull/20435/commits/3a3b9f31fc1c672c63dfc8ef02108bc2ee0eb563#diff-19743365133d63884e16c2ed111a9076bb50a34785a3e624bd4abf49d49f814c
                    */}

                    {/* if free ONLY */}

                    <Section title="Contact support">
                        <p>
                            Due to the volume of messages and our limited team size, we're unable to offer email support
                            about account-specific issues to free plans. But we still want to help!
                        </p>

                        <ol className="pl-5">
                            <li>
                                <strong className="block">Search our docs</strong>
                                <p>
                                    We're constantly updating our docs and tutorials to provide the latest information
                                    about installing, using, and troubleshooting.
                                </p>
                            </li>
                            <li>
                                <strong className="block">Ask a community question</strong>
                                <p>
                                    Many common (and niche) questions have already been resolved. (Our own engineers
                                    also keep an eye on the questions as they have time!){' '}
                                    <Link to="https://posthog.com/question" className="block">
                                        Search community questions or ask your own.
                                    </Link>
                                </p>
                            </li>
                            <li>
                                <strong className="block">
                                    Explore <Link to="https://posthog.com/partners">PostHog partners</Link>
                                </strong>
                                <p>Third-party providers can help with installation and debugging of data issues.</p>
                            </li>
                            <li>
                                <strong className="block">Upgrade to a paid plan</strong>
                                <p>
                                    Our paid plans offer email support.{' '}
                                    <Link to="https://posthog.com/pricing">Explore options</Link>
                                </p>
                            </li>
                        </ol>
                    </Section>

                    {/* if paid ONLY */}
                    <Section title="More options">
                        <p>
                            Can't find what you need in the docs? <Link>Email an engineer</Link>
                        </p>

                        {/* show below when "Email an engineer" is clicked */}
                        <div className="grid grid-cols-2 border [&_>*]:px-2 [&_>*]:py-0.5 mb-4">
                            <div className="col-span-full flex justify-between border-b">
                                <div>Avg support response times</div>
                                <div>
                                    <Link to="#">Explore options</Link>
                                </div>
                            </div>
                            <div>Free</div>
                            <div className="">Community support only</div>
                            <div className="font-bold">
                                Pay per use <span className="font-normal opacity-60 text-sm">(your plan)</span>
                            </div>
                            <div className="font-bold">12-24 hours</div>
                            <div>Teams plan</div>
                            <div>4-6 hours</div>
                        </div>
                        <SupportForm />
                    </Section>

                    <footer>
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
                            onClick={closeSupportForm}
                            fullWidth
                            center
                            className="mt-2"
                        >
                            Cancel
                        </LemonButton>
                    </footer>
                </div>
            </div>
        </>
    )
}
