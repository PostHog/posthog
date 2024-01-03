import './PayGatePage.scss'

import { IconCheckCircle, IconOpenSidebar } from '@posthog/icons'
import { useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { identifierToHuman } from 'lib/utils'
import { billingLogic } from 'scenes/billing/billingLogic'

import { AvailableFeature } from '~/types'

const AbTestingPaidFeatures = [
    'A/B testing suite',
    'Group experiments',
    'Funnel & trend experiments',
    'Secondary experiment metrics',
    'Statistical analysis',
    '7 year data retention',
]

const AbTestingFeatures = [
    {
        name: 'Customizable goals',
        description: 'Conversion funnels or trends, secondary metrics, and range for statistical significance',
        // image: <StaticImage src="./images/goals.png" width={428} />,
        image: 'https://posthog.com/images/products/ab-testing.png',
    },
    {
        name: 'Targeting & exclusion rules',
        description: 'Set criteria for user location, user property, cohort, or group',
        // image: <StaticImage src="./images/targeting-ab.png" width={428} />,
        image: 'https://posthog.com/images/products/ab-testing.png',
    },
    {
        name: 'Recommendations',
        description: 'Automatic suggestions for duration, sample size, and confidence threshold in a winning variant',
        // image: <StaticImage src="./images/recommendations.png" width={428} />,
        image: 'https://posthog.com/images/products/ab-testing.png',
    },
]

interface FeatureProps {
    name: string
    description: string
    image: any
}

export const Feature = ({ name, description, image }: FeatureProps): JSX.Element => {
    return (
        <li className="text-center">
            <div className={`mb-2 w-full`}>
                <img src={image} className="w-full" />
            </div>
            <h4 className="mb-1 leading-tight text-lg">{name}</h4>
            <p className="text-[15px]" dangerouslySetInnerHTML={{ __html: description }} />
        </li>
    )
}

interface PayGatePageInterface {
    header: string | JSX.Element
    caption: string | JSX.Element
    hideUpgradeButton?: boolean
    docsLink?: string // Link to the docs of the feature, if no link is sent, it will be hidden
    featureKey: AvailableFeature
    featureName?: string
}

export function PayGatePage({
    header,
    caption,
    hideUpgradeButton,
    docsLink,
    featureKey,
    featureName,
}: PayGatePageInterface): JSX.Element {
    const { upgradeLink } = useValues(billingLogic)
    featureName = featureName || identifierToHuman(featureKey, 'title')

    return (
        <>
            <div className="pay-gate-page">
                <h2>{header}</h2>
                <div className="pay-caption">{caption}</div>
                <div className="pay-buttons space-y-4">
                    {!hideUpgradeButton && (
                        <LemonButton to={upgradeLink} type="primary" data-attr={`${featureKey}-upgrade`} center>
                            Upgrade now to get {featureName}
                        </LemonButton>
                    )}
                    {docsLink && (
                        <LemonButton
                            type={hideUpgradeButton ? 'primary' : 'secondary'}
                            to={`${docsLink}?utm_medium=in-product&utm_campaign=${featureKey}-upgrade-learn-more`}
                            targetBlank
                            center
                            data-attr={`${featureKey}-learn-more`}
                        >
                            Learn more {<IconOpenSidebar className="ml-2" />}
                        </LemonButton>
                    )}
                </div>
            </div>
            <div className="unsubscribed-product-landing-page">
                <header className="grid grid-cols-2 items-center gap-8">
                    <div className="px-8">
                        <h2 className="text-2xl font-bold">A/B testing</h2>
                        <p className="text-base font-bold">Test changes with statistical significance</p>
                        <p>
                            Run A/B tests and multivariate tests with robust targeting & exclusion rules. Analyze usage
                            with product analytics and session replay.
                        </p>
                    </div>
                    <aside className="text-right">
                        <img src="https://posthog.com/images/products/ab-testing.png" className="max-w-full" />
                    </aside>
                </header>
                <div className="flex gap-12 p-8">
                    <div className="flex-1">
                        <h3>Get started running experiments</h3>
                        <p>
                            Your first 1,000,000 monthly feature flag requests are free. (Feature flags power A/B
                            testing!) Only pay if you exceed this volume, and{' '}
                            <strong>you can still set a billing limit to never receive an unexpected bill.</strong>
                        </p>
                        <p>
                            <strong>First 1 million requests are free every month</strong>, then starts at
                            $0.000100/request
                        </p>
                        <p>
                            <span className="">Show volume discounts</span>
                        </p>
                        <div className="flex">
                            <LemonButton
                                to={upgradeLink}
                                type="primary"
                                status="alt"
                                data-attr={`${featureKey}-upgrade`}
                                center
                                className="self-start"
                            >
                                Set up {featureName} - free
                            </LemonButton>
                        </div>
                    </div>
                    <div className="shrink-0">
                        <p>
                            <strong>Use for free, or upgrade to get:</strong>
                        </p>
                        <ul className="space-y-1">
                            {AbTestingPaidFeatures.map((feature, index) => (
                                <li key={index} className="flex gap-1.5 items-center leading-0">
                                    <span className="text-greeen">
                                        <IconCheckCircle className="text-2xl fill-current" />
                                    </span>
                                    <span>{feature}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
                <div className="features p-8 py-12">
                    <h3 className="mb-4">Features</h3>
                    <ul className="list-none p-0 grid grid-cols-3 gap-8">
                        {AbTestingFeatures.map((feature, index) => {
                            return <Feature {...feature} key={index} />
                        })}
                    </ul>
                </div>
            </div>
        </>
    )
}
