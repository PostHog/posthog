import './PayGatePage.scss'

import { IconOpenSidebar } from '@posthog/icons'
import { IconCheckCircle } from '@posthog/icons'
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
                    <aside>
                        <img
                            src="https://posthog.com/static/2beccf3e3a0dc26babd46bff2358581e/70464/ab-testing-hog.webp"
                            className="max-w-full"
                        />
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
                        <LemonButton
                            to={upgradeLink}
                            type="primary"
                            status="alt"
                            data-attr={`${featureKey}-upgrade`}
                            center
                        >
                            Set up {featureName} - free
                        </LemonButton>
                    </div>
                    <div className="shrink-0">
                        <p>
                            <strong>Use for free, or upgrade to get:</strong>
                        </p>
                        <ul>
                            {AbTestingPaidFeatures.map((feature, index) => (
                                <li key={index} className="flex gap-1 items-center">
                                    <span className="text-green">
                                        <IconCheckCircle className="text-xl fill-current" />
                                    </span>
                                    <span>{feature}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
                <div className="features py-12">
                    <h3 className="mb-4">Features</h3>
                    <ul className="grid grid-cols-3 gap-8">
                        <li>feature 1</li>
                        <li>feature 2</li>
                        <li>feature 3</li>
                        <li>feature 4</li>
                        <li>feature 5</li>
                        <li>feature 5</li>
                        <li>feature 7</li>
                    </ul>
                </div>
            </div>
        </>
    )
}
