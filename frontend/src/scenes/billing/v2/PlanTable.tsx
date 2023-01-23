import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconArrowRight, IconCheckmark, IconClose, IconWarning } from 'lib/components/icons'
import { LemonSnack } from 'lib/components/LemonSnack/LemonSnack'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingV2Logic } from './billingV2Logic'
import './PlanTable.scss'

export type Product = {
    name: string
    note?: string
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
                note: 'Limited to 1M events/mo',
                subfeatures: [
                    {
                        name: 'Graphs & trends',
                        value: true,
                    },
                    {
                        name: 'Funnels',
                        value: 'limited functionality',
                        note: 'Limited',
                    },
                    {
                        name: 'Path analysis',
                        value: 'limited functionality',
                        note: 'Limited',
                    },
                    {
                        name: 'Dashboards',
                        value: '1 dashboard',
                        note: '1 dashboard',
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
                note: 'Limited to 15,000 recordings/mo',
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
                note: 'Priced per event',
                tiers: [
                    {
                        description: 'Up to 1 million events/mo',
                        price: 'Free',
                    },
                ],
            },
            {
                name: 'Session recording',
                note: 'Priced per recording',
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

export function PlanIcon({
    value,
    note,
    className,
}: {
    value: boolean | string
    note?: string
    className?: string
}): JSX.Element {
    return (
        <div className="flex items-center text-xs text-muted">
            {value === true ? (
                <>
                    <IconCheckmark className={`text-success mr-4 ${className}`} />
                    {note}
                </>
            ) : value === false ? (
                <>
                    <IconClose className={`text-danger mr-4 ${className}`} />
                    {note}
                </>
            ) : (
                <>
                    <IconWarning className={`text-warning mr-4 ${className}`} />
                    {note}
                </>
            )}
        </div>
    )
}

export function PlanTable({ redirectPath }: { redirectPath: string }): JSX.Element {
    const { billing } = useValues(billingV2Logic)
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)

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
        <div className="PlanTable space-x-4">
            <table className="w-full table-fixed">
                <thead>
                    <tr>
                        <td />
                        {billingPlans.map((plan) => (
                            <td key={plan.name}>
                                <h3 className="font-bold">{plan.name}</h3>
                                <p className="ml-0 text-xs">{plan.description}</p>
                                {featureFlags[FEATURE_FLAGS.BILLING_PLAN_MOST_POPULAR_EXPERIMENT] === 'test' &&
                                plan.name === 'PostHog Cloud' ? (
                                    <LemonSnack className="text-xs mt-1">Most popular</LemonSnack>
                                ) : null}
                            </td>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <th
                            colSpan={4}
                            className="PlanTable__th__section bg-muted-light text-muted justify-left rounded text-left mb-2"
                        >
                            <span>Pricing</span>
                        </th>
                    </tr>
                    <tr className="PlanTable__tr__border">
                        <td className="font-bold">Monthly base price</td>
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
                                i !== Object.keys(billingPlans[0].products).length - 1 ? 'PlanTable__tr__border' : ''
                            }
                        >
                            <th scope="row">
                                {billingPlans[0].products[product].name}
                                <p className="ml-0 text-xs text-muted mt-1">{billingPlans[0].products[product].note}</p>
                            </th>
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
                            className="PlanTable__th__section bg-muted-light text-muted justify-left rounded text-left mb-2"
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
                        <>
                            <tr
                                key={feature}
                                className={
                                    // Show the bottom border if it's not the last feature in the list and it doesn't have subfeatures
                                    i !== Object.keys(billingPlans[0].featureList).length - 1 &&
                                    !billingPlans[0].featureList[feature].subfeatures
                                        ? 'PlanTable__tr__border'
                                        : ''
                                }
                            >
                                <th>{billingPlans[0].featureList[feature].name}</th>
                                {billingPlans.map((plan) => (
                                    <td key={`${plan.name}-${feature}`}>
                                        <PlanIcon
                                            value={plan.featureList[feature].value}
                                            note={plan.featureList[feature].note}
                                            className={'text-xl'}
                                        />
                                    </td>
                                ))}
                            </tr>
                            {billingPlans[0].featureList[feature].subfeatures
                                ? Object.keys(billingPlans[0].featureList[feature].subfeatures).map((subfeature, j) => (
                                      <tr
                                          key={subfeature}
                                          className={
                                              // Show the bottom border on the row if it's the last subfeature in the list
                                              j ===
                                              Object.keys(billingPlans[0].featureList[feature].subfeatures).length - 1
                                                  ? 'PlanTable__tr__border'
                                                  : ''
                                          }
                                      >
                                          <th className="PlanTable__th__subfeature text-muted text-xs">
                                              {billingPlans[0].featureList[feature].subfeatures[subfeature].name}
                                          </th>
                                          {billingPlans.map((plan) => (
                                              <td key={`${plan.name}-${subfeature}`}>
                                                  <PlanIcon
                                                      value={plan.featureList[feature].subfeatures[subfeature]?.value}
                                                      note={plan.featureList[feature].subfeatures[subfeature]?.note}
                                                      className={'text-base'}
                                                  />
                                              </td>
                                          ))}
                                      </tr>
                                  ))
                                : null}
                        </>
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
