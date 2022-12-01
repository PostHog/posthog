import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
import { Card } from 'antd'
import { useValues } from 'kea'
import { IconArrowRight, IconBarChart, IconCheckmark, IconRecording } from 'lib/components/icons'
import { LemonSnack } from 'lib/components/LemonSnack/LemonSnack'
import { billingTestLogic } from './billingTestLogic'
import './PlanCards.scss'

export type BillingPlan = {
    name: string
    description: string
    pricingDescription: string
    features: string[]
    cta: string
    signupLink: string
    products: Product[]
}

export type Product = {
    name: string
    startingPrice: number
    unit: string
    note?: string
    icon: JSX.Element
    features: string[]
}

export const billingPlans: BillingPlan[] = [
    {
        name: 'Free',
        description: 'Free forever.',
        pricingDescription: '',
        features: ['Community support'],
        cta: 'Downgrade',
        signupLink: '/api/billing-v2/activation?plan=free',
        products: [
            {
                name: 'Product analytics + data stack',
                startingPrice: 0,
                unit: 'event',
                // note: 'Up to 1M per month',
                icon: <IconBarChart />,
                features: ['Up to 1M events per month', '1 project', '1 dashboard', '10 feature flags'],
            },
            {
                name: 'Session Recordings',
                startingPrice: 0,
                unit: 'recording',
                // note: 'Up to 15,000 per month',
                icon: <IconRecording />,
                features: ['Up to 15,000 recordings per month'],
            },
        ],
    },
    {
        name: 'Scale',
        description: 'For businesses who want to leverage their data.',
        pricingDescription: '',
        features: ['Unlimited projects', 'Unlimited experiments', 'Unlimited Feature flags', 'Community support'],
        cta: 'Upgrade',
        signupLink: '/api/billing-v2/activation?plan=standard',
        products: [
            {
                name: 'Product analytics + data stack',
                startingPrice: 0.00045,
                unit: 'event',
                note: 'First 1 million events/mo free',
                icon: <IconBarChart />,
                features: [
                    'Unlimited dashboards',
                    'Unlimited insights',
                    'Funnels & trends',
                    'Cohorts & retention',
                    'Path analysis, and more...',
                ],
            },
            {
                name: 'Session Recordings',
                startingPrice: 0.005,
                unit: 'recording',
                note: 'First 15,000 recordings/mo free',
                icon: <IconRecording />,
                features: ['Saved playlists', 'Console logs'],
            },
        ],
    },
    {
        name: 'Enterprise',
        description: 'Advanced features for enterprises.',
        pricingDescription: '',
        features: [
            'Everything in Scale, plus...',
            'SAML SSO',
            'Advanced permissions',
            'Dedicated support via Slack',
            '$450/mo minimum',
        ],
        cta: 'Upgrade',
        signupLink: '/api/billing-v2/activation?plan=enterprise',
        products: [
            {
                name: 'Product analytics + data stack',
                startingPrice: 0.0005625,
                unit: 'event',
                note: 'First 1 million events/mo free',
                icon: <IconBarChart />,
                features: ['Everything in Scale'],
            },
            {
                name: 'Session Recordings',
                startingPrice: 0.00625,
                unit: 'recording',
                note: 'First 15,000 recordings/mo free',
                icon: <IconRecording />,
                features: ['Everything in Scale'],
            },
        ],
    },
]

export function PlanCards({ redirectPath }: { redirectPath: string }): JSX.Element {
    const { billing } = useValues(billingTestLogic)
    return (
        <div className="PlanCards space-x-4">
            {billingPlans.map((plan) => (
                <div key={plan.name}>
                    <Card className={`${plan.name === 'Scale' ? 'border-primary' : 'border-primary-extralight'} p-6`}>
                        <div className="mt-4">
                            <div className="flex justify-between items-center">
                                <h2 className="font-bold">{plan.name}</h2>
                                {plan.name === 'Scale' ? (
                                    <LemonSnack className="text-xs mb-2">Most Popular</LemonSnack>
                                ) : null}
                            </div>
                            <p className="mx-0">{plan.description}</p>
                            <LemonButton
                                to={`${plan.signupLink}&redirect_path=${redirectPath}`}
                                type={plan.name === 'Free' || plan.name === 'Enterprise' ? 'secondary' : 'primary'}
                                fullWidth
                                center
                                disableClientSideRouting
                                disabled={plan.name === 'Free' && !billing?.billing_period}
                            >
                                {!billing?.billing_period && plan.name === 'Free' ? 'Current plan' : plan.cta}
                            </LemonButton>
                        </div>
                        <LemonDivider className="my-6" />
                        <div className="">
                            <h3>Platform</h3>
                            <ul className="pl-6 mt-4 mb-8">
                                {plan.features.map((feature) => (
                                    <li key={feature} className="mb-3 text-base flex items-center">
                                        <IconCheckmark className="text-primary mr-4 text-lg" />
                                        {feature}
                                    </li>
                                ))}
                            </ul>
                            <h3>Products</h3>
                            <ul className="mt-4 mb-8">
                                {plan.products.map((product) => (
                                    <li key={product.name} className="mb-4 text-base bg-muted-light rounded p-6 flex">
                                        <div className="text-3xl mr-4">{product.icon}</div>
                                        <div className="my-1">
                                            <h4 className="text-sm text-muted mb-1">{product.name}</h4>
                                            <p className="mb-0 ml-0">
                                                <span className="font-bold text-lg">${product.startingPrice}</span>
                                                <span className="text-xs">/{product.unit}</span>
                                            </p>
                                            {product.note ? (
                                                <p className="ml-0 mb-0 text-xs text-muted">{product.note}</p>
                                            ) : null}
                                            <ul className="mt-4">
                                                {product.features.map((feature) => (
                                                    <li key={feature} className="mb-3 text-base flex items-center">
                                                        <IconCheckmark className="text-primary mr-4 text-lg" />
                                                        {feature}
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    </li>
                                ))}
                            </ul>
                            <div className="text-center">
                                <Link to="https://posthog.com/pricing" className="text-muted" target="_blank">
                                    Learn more about our pricing <IconArrowRight />
                                </Link>
                            </div>
                        </div>
                    </Card>
                </div>
            ))}
        </div>
    )
}
