import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconArrowRight, IconCheckmark, IconClose, IconWarning } from 'lib/components/icons'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingTestLogic } from './billingTestLogic'
import './PlanTable.scss'

export type Product = {
    name: string
    tiers: {
        description: string
        price: string
    }[]
}

export type Feature = {
    name: string
    value: boolean | string
    note?: string
    subfeatures?: Feature[]
}

export type FeatureList = {
    productAnalytics: Feature
    sessionRecording: Feature
    projects: Feature
    experiments: Feature
    multivariateFFs: Feature
    prioritySupport: Feature
    advancedPermissions: Feature
    sso: Feature
}

export type BillingPlan = {
    name: string
    description: string
    pricingDescription: string
    basePrice: string
    cta: string
    signupLink: string
    featureList: FeatureList
    products: Product[]
}

export const billingPlans: BillingPlan[] = [
    {
        name: 'PostHog Cloud Lite',
        description: 'For hobbyists and early-stage startups. Community-based support.',
        pricingDescription: 'Free',
        basePrice: 'Free',
        cta: 'Downgrade',
        signupLink: '/api/billing-v2/activation?plan=free',
        featureList: {
            productAnalytics: {
                name: 'Product analytics',
                value: 'limited functionality',
                note: '1M limit/mo',
                subfeatures: [
                    {
                        name: 'Graphs & trends',
                        value: true,
                    },
                    {
                        name: 'Funnels',
                        value: 'limited functionality',
                    },
                    {
                        name: 'Path analysis',
                        value: 'limited functionality',
                    },
                    {
                        name: 'Dashboards',
                        value: '1 dashboard',
                        note: '1 dashbaord',
                    },
                    {
                        name: 'Group analytics',
                        value: false,
                    },
                ],
            },
            sessionRecording: {
                name: 'Session recording',
                value: '15,000 limit',
                note: '15,000 limit/mo',
            },
            projects: {
                name: 'Projects',
                value: '1 project',
                note: '1 project',
            },
            experiments: {
                name: 'A/B testing',
                value: false,
            },
            multivariateFFs: {
                name: 'Multivariate feature flags',
                value: false,
            },
            prioritySupport: {
                name: 'Priority support',
                value: false,
            },
            advancedPermissions: {
                name: 'Advanced permissions',
                value: false,
            },
            sso: {
                name: 'SAML SSO',
                value: false,
            },
        },
        products: [
            {
                name: 'Product analytics',
                tiers: [
                    {
                        description: 'Up to 1 million events/mo',
                        price: 'Free',
                    },
                ],
            },
            {
                name: 'Session recording',
                tiers: [
                    {
                        description: 'Up to 15,000 recordings/mo',
                        price: 'Free',
                    },
                ],
            },
        ],
    },
    {
        name: 'PostHog Cloud',
        description: 'The whole hog. Email support.',
        pricingDescription: 'Usage-based pricing',
        basePrice: '$0/mo',
        cta: 'Upgrade',
        signupLink: '/api/billing-v2/activation?plan=standard',
        featureList: {
            productAnalytics: {
                name: 'Product analytics',
                value: true,
                note: 'Unlimited',
                subfeatures: [
                    {
                        name: 'Graphs & trends',
                        value: true,
                    },
                    {
                        name: 'Funnels',
                        value: true,
                    },
                    {
                        name: 'Path analysis',
                        value: true,
                    },
                    {
                        name: 'Dashboards',
                        value: true,
                    },
                    {
                        name: 'Group analytics',
                        value: true,
                    },
                ],
            },
            sessionRecording: {
                name: 'Session Recording',
                value: true,
                note: 'Unlimited',
            },
            projects: {
                name: 'Projects',
                value: true,
                note: 'Unlimited',
            },
            experiments: {
                name: 'A/B testing',
                value: true,
            },
            multivariateFFs: {
                name: 'Multivariate feature flags',
                value: true,
            },
            prioritySupport: {
                name: 'Priority support',
                value: true,
            },
            advancedPermissions: {
                name: 'Advanced permissions',
                value: 'Project permissions only',
                note: 'Projects only',
            },
            sso: {
                name: 'SAML SSO',
                value: false,
            },
        },
        products: [
            {
                name: 'Product analytics',
                tiers: [
                    {
                        description: 'First 1 million events/mo',
                        price: 'Free',
                    },
                    {
                        description: '1-2 million',
                        price: '$0.00045',
                    },
                ],
            },
            {
                name: 'Session recording',
                tiers: [
                    {
                        description: 'First 15,000 recordings/mo',
                        price: 'Free',
                    },
                    {
                        description: '15,000-50,000',
                        price: '$0.0050',
                    },
                ],
            },
        ],
    },
    {
        name: 'PostHog Enterprise Cloud',
        description: 'SSO and advanced permissions. Dedicated Slack-based support.',
        pricingDescription: 'Usage-based pricing',
        basePrice: '$450/mo min',
        cta: 'Upgrade',
        signupLink: '/api/billing-v2/activation?plan=enterprise',
        featureList: {
            productAnalytics: {
                name: 'Product analytics',
                value: true,
                note: 'Unlimited',
                subfeatures: [
                    {
                        name: 'Graphs & trends',
                        value: true,
                    },
                    {
                        name: 'Funnels',
                        value: true,
                    },
                    {
                        name: 'Path analysis',
                        value: true,
                    },
                    {
                        name: 'Dashboards',
                        value: true,
                    },
                    {
                        name: 'Group analytics',
                        value: true,
                    },
                ],
            },
            sessionRecording: {
                name: 'Session Recording',
                value: true,
                note: 'Unlimited',
            },
            projects: {
                name: 'Projects',
                value: true,
                note: 'Unlimited',
            },
            experiments: {
                name: 'A/B testing',
                value: true,
            },
            multivariateFFs: {
                name: 'Multivariate feature flags',
                value: true,
            },
            prioritySupport: {
                name: 'Priority support',
                value: true,
                note: 'via Slack',
            },
            advancedPermissions: {
                name: 'Advanced permissions',
                value: true,
            },
            sso: {
                name: 'SAML SSO',
                value: true,
            },
        },
        products: [
            {
                name: 'Product analytics',
                tiers: [
                    {
                        description: 'First 1 million events/mo',
                        price: 'Included',
                    },
                    {
                        description: '1-2 million',
                        price: '$0.0005625',
                    },
                ],
            },
            {
                name: 'Session recording',
                tiers: [
                    {
                        description: 'First 15,000 recordings/mo',
                        price: 'Included',
                    },
                    {
                        description: '15,000-50,000',
                        price: '$0.00625',
                    },
                ],
            },
        ],
    },
]

export function PlanTable({ redirectPath }: { redirectPath: string }): JSX.Element {
    const { billing } = useValues(billingTestLogic)
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)

    const upgradeButtons = billingPlans.map((plan) => (
        <td key={`${plan.name}-cta`}>
            <LemonButton
                to={`${plan.signupLink}&redirect_path=${redirectPath}`}
                type={plan.name === 'PostHog Cloud Lite' ? 'secondary' : 'primary'}
                fullWidth
                center
                disableClientSideRouting
                disabled={plan.name === 'PostHog Cloud Lite' && !billing?.billing_period}
                onClick={() => {
                    if (plan.name != 'PostHog Cloud Lite') {
                        reportBillingUpgradeClicked(plan.name)
                    }
                }}
            >
                {!billing?.billing_period && plan.name === 'PostHog Cloud Lite' ? 'Current plan' : plan.cta}
            </LemonButton>
        </td>
    ))

    return (
        <div className="PlanCards space-x-4">
            <table className="w-full table-fixed">
                <thead>
                    <tr>
                        <td />
                        {billingPlans.map((plan) => (
                            <td key={plan.name}>
                                <h3 className="font-bold">{plan.name}</h3>
                                <p className="ml-0 text-xs">{plan.description}</p>
                            </td>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <th
                            colSpan={4}
                            className="PlansCards__th__section bg-muted-light text-muted justify-left rounded text-left mb-2"
                        >
                            <span>Pricing</span>
                        </th>
                    </tr>
                    <tr className="PlanCards__tr__border">
                        <td className="font-bold">Monthly Base Price</td>
                        {billingPlans.map((plan) => (
                            <td key={`${plan.name}-basePrice`} className="text-sm font-bold">
                                {plan.basePrice}
                            </td>
                        ))}
                    </tr>
                    {Object.keys(billingPlans[0].products).map((product, i) => (
                        <tr
                            key={product}
                            className={
                                i !== Object.keys(billingPlans[0].products).length - 1 ? 'PlanCards__tr__border' : ''
                            }
                        >
                            <th scope="row">{billingPlans[0].products[product].name}</th>
                            {billingPlans.map((plan) => (
                                <td key={`${plan.name}-${product}`}>
                                    {plan.products[i].tiers.map((tier) => (
                                        <div
                                            key={`${plan.name}-${product}-${tier.description}`}
                                            className="flex justify-between items-center"
                                        >
                                            <span className="text-xs">{tier.description}</span>
                                            <span className="font-bold">{tier.price}</span>
                                        </div>
                                    ))}
                                    {plan.name !== 'PostHog Cloud Lite' ? (
                                        <Link
                                            to="https://posthog.com/pricing"
                                            target="_blank"
                                            className="text-xs font-semibold"
                                        >
                                            More volume tiers
                                        </Link>
                                    ) : null}
                                </td>
                            ))}
                        </tr>
                    ))}
                    <tr>
                        <td />
                        {upgradeButtons}
                    </tr>
                    <tr>
                        <th
                            colSpan={4}
                            className="PlansCards__th__section bg-muted-light text-muted justify-left rounded text-left mb-2"
                        >
                            <div className="flex justify-between items-center">
                                <span>Features</span>
                                <span>
                                    <Link
                                        to="https://posthog.com/pricing"
                                        target="_blank"
                                        className="text-xs text-muted italic"
                                    >
                                        Full feature comparison <IconArrowRight />
                                    </Link>
                                </span>
                            </div>
                        </th>
                    </tr>
                    {Object.keys(billingPlans[0].featureList).map((feature, i) => (
                        <tr
                            key={feature}
                            className={
                                i !== Object.keys(billingPlans[0].featureList).length - 1 ? 'PlanCards__tr__border' : ''
                            }
                        >
                            <th>{billingPlans[0].featureList[feature].name || 'Product analytics'}</th>
                            {billingPlans.map((plan) => (
                                <td key={`${plan.name}-${feature}`}>
                                    <div className="flex items-center">
                                        {plan.featureList[feature].value === true ? (
                                            <>
                                                <IconCheckmark className="text-success text-xl mr-4" />
                                                {plan.featureList[feature].note}
                                            </>
                                        ) : plan.featureList[feature].value === false ? (
                                            <>
                                                <IconClose className="text-danger text-xl" />
                                                {plan.featureList[feature].note}
                                            </>
                                        ) : (
                                            <>
                                                <IconWarning className="text-warning text-xl mr-4" />
                                                {plan.featureList[feature].note}
                                            </>
                                        )}
                                    </div>
                                </td>
                            ))}
                        </tr>
                    ))}
                    <tr>
                        <td />
                        {upgradeButtons}
                    </tr>
                </tbody>
            </table>
        </div>
    )
}
