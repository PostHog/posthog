import {
    IconBolt,
    IconDatabase,
    IconFeatures,
    IconFlag,
    IconHeart,
    IconLock,
    IconPrivacy,
    IconSupport,
    IconTrending,
    IconUpload,
} from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { ExperimentsHog } from 'lib/components/hedgehogs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: moveToPostHogCloud,
}

type CloudFeature = {
    name: string
    description: string
    icon: JSX.Element
    link?: string
}

export function moveToPostHogCloud(): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)
    if (isCloudOrDev) {
        router.actions.push(urls.default())
    }
    const cloudFeatures: CloudFeature[] = [
        {
            name: 'Hosted for you',
            description: "No need to worry about servers, databases, or data ingestion. We've got it all covered.",
            icon: <IconDatabase />,
        },
        {
            name: 'EU and US data centers',
            description: 'Host your data in the EU or US, whichever works best for your customer base.',
            icon: <IconFlag />,
        },
        {
            name: 'Easy migration',
            description:
                "We've done this before. It's just a few clicks to get your data moving from self-hosted to Cloud.",
            icon: <IconUpload />,
            link: 'https://posthog.com/docs/migrate/migrate-to-cloud',
        },
        {
            name: 'Auto-scaling',
            description:
                'As your product grows, so does your data, and scaling can be tough. On PostHog Cloud we take care of it for you so you never have to worry about spikes or downtime.',
            icon: <IconTrending />,
        },
        {
            name: 'Highly available',
            description:
                'PostHog Cloud is highly available, so you can rest easy knowing your data is always accessible.',
            icon: <IconBolt />,
        },
        {
            name: 'Automatic upgrades',
            description:
                'PostHog Cloud is always up to date with the latest features and security updates - no upgrades required.',
            icon: <IconUpload />,
        },
        {
            name: 'Automatic backups',
            description: "Don't worry about backups - we've got it covered.",
            icon: <IconLock />,
        },
        {
            name: 'Access to all features',
            description:
                'Group analytics, data pipelines, A/B testing, and all other premium features are all available on PostHog Cloud.',
            icon: <IconFeatures />,
            link: 'https://posthog.com/pricing',
        },
        {
            name: 'World-class support',
            description:
                'We unforunately cannot offer support for self-hosted instances. PostHog Cloud customers get access to our world-class support team.',
            icon: <IconSupport />,
            link: 'https://posthog.com/handbook/growth/customer-support',
        },
        {
            name: 'SOC 2 compliant',
            description: "We're SOC-2 compliant, so you can rest easy knowing your data is secure.",
            icon: <IconPrivacy />,
            link: 'https://posthog.com/handbook/company/security',
        },
        {
            name: 'HIPAA compliant (coming soon)',
            description:
                "We'll be HIPAA compliant very soon (just waiting on paperwork), so you can rest easy knowing your data is secure.",
            icon: <IconHeart />,
        },
    ]

    return (
        <div className="-m-4">
            <header className="bg-primary-alt-highlight border-b border-t border-border flex justify-center p-8">
                <div className="grid md:grid-cols-2 items-center gap-8 w-full max-w-screen-xl">
                    <div className="">
                        <h2 className="text-2xl font-bold">PostHog Cloud</h2>
                        <h3 className="text-4xl font-bold tracking-tight">
                            We handle the infra. You focus on your product.
                        </h3>
                        <p>
                            Hosting PostHog is no easy feat. It takes a lot of domain nowledge to get it right -
                            especially at scale. Let us handle the hosting, so you can focus on building your product.
                        </p>
                        <div className="flex">
                            <LemonButton
                                to="https://us.posthog.com/signup?utm_medium=in-product&utm_campaign=move-to-cloud"
                                type="primary"
                                status="alt"
                            >
                                Move to PostHog Cloud
                            </LemonButton>
                        </div>
                    </div>
                    <aside className="my-2 hidden md:flex justify-end">
                        <div className="max-w-64">
                            <ExperimentsHog className="w-full h-auto" />
                        </div>
                    </aside>
                </div>
            </header>
            <div className="p-8 py-8 border-t border-border flex justify-center">
                <div className="max-w-screen-xl">
                    <h3 className="mb-6 text-2xl font-bold">Features</h3>
                    <ul className="list-none p-0 grid sm:grid-cols-2 md:grid-cols-3 gap-8 mb-8 ">
                        {cloudFeatures.map((feature, i) => {
                            return (
                                <li
                                    className="rounded-lg p-4 sm:p-6 sm:pb-8 bg-primary-alt-highlight"
                                    key={`subfeature-${i}`}
                                >
                                    <span className="inline-block text-2xl mb-2 opacity-75">{feature.icon}</span>
                                    <h3 className="text-[17px] mb-1 leading-tight">{feature.name}</h3>
                                    <p className="m-0 text-[15px]">{feature.description}</p>
                                    {feature.link && (
                                        <p className="mt-1">
                                            <Link to={feature.link}>Learn more</Link>
                                        </p>
                                    )}
                                </li>
                            )
                        })}
                    </ul>
                </div>
            </div>
        </div>
    )
}
