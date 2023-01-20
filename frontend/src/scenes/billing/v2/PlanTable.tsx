import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconCheckmark, IconClose, IconWarning } from 'lib/components/icons'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { Tooltip } from 'lib/components/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { BillingProductV2Type, BillingV2FeatureType, BillingV2PlanType } from '~/types'
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
    feature,
    className,
    timeDenominator,
}: {
    feature?: BillingV2FeatureType
    className?: string
    timeDenominator?: string
}): JSX.Element {
    return (
        <div className="flex items-center text-xs text-muted">
            {!feature ? (
                <>
                    <IconClose className={`text-danger mr-4 ${className}`} />
                </>
            ) : feature.limit ? (
                <>
                    <IconWarning className={`text-warning mr-4 ${className}`} />
                    {feature.limit &&
                        `${convertLargeNumberToWords(feature.limit, null)} ${feature.unit && feature.unit}${
                            timeDenominator ? `/${timeDenominator}` : ''
                        }`}
                    {feature.note}
                </>
            ) : (
                <>
                    <IconCheckmark className={`text-success mr-4 ${className}`} />
                    {feature.note}
                </>
            )}
        </div>
    )
}

const getPlanBasePrice = (plan: BillingV2PlanType): number | string => {
    const basePlan = plan.products.find((product) => product.type === 'enterprise' || product.type === 'base')
    if (basePlan?.unit_amount_usd) {
        return `$${parseInt(basePlan.unit_amount_usd)}/mo`
    }
    if (plan.name === 'Starter') {
        return 'Free forever'
    }
    return '$0/mo'
}

const convertLargeNumberToWords = (
    // The number to convert
    num: number | null,
    // The previous tier's number
    previousNum: number | null,
    // Whether we will be showing multiple tiers (to denote the first tier with 'first')
    multipleTiers: boolean = false,
    // The product type (to denote the unit)
    productType: BillingProductV2Type['type'] | null = null
): string => {
    if (num === null && previousNum) {
        return `${convertLargeNumberToWords(previousNum, null)} +`
    }
    if (num === null) {
        return ''
    }

    let denominator = 1

    if (num >= 1000000) {
        denominator = 1000000
    } else if (num >= 1000) {
        denominator = 1000
    }

    return `${previousNum ? `${(previousNum / denominator).toFixed(0)}-` : multipleTiers ? 'First ' : ''}${(
        num / denominator
    ).toFixed(0)}${denominator === 1000000 ? ' million' : denominator === 1000 ? 'k' : ''}${
        !previousNum && multipleTiers ? ` ${productType}/mo` : ''
    }`
}

const getProductTiers = (plan: BillingV2PlanType, productType: BillingProductV2Type['type']): JSX.Element => {
    const product = plan.products.find((planProduct) => planProduct.type === productType)
    const tiers = product?.tiers
    return (
        <>
            {tiers ? (
                tiers?.map((tier, i) => (
                    <div
                        key={`${plan.name}-${productType}-${tier.up_to}`}
                        className="flex justify-between items-center"
                    >
                        <span className="text-xs">
                            {convertLargeNumberToWords(tier.up_to, tiers[i - 1]?.up_to, true, productType)}
                        </span>
                        <span className="font-bold">
                            {i === 0 && parseFloat(tier.unit_amount_usd) === 0
                                ? plan.name === 'Scale'
                                    ? 'Free'
                                    : 'Included'
                                : `$${parseFloat(tier.unit_amount_usd).toFixed(6)}`}
                        </span>
                    </div>
                ))
            ) : product?.free_allocation ? (
                <div key={`${plan.name}-${productType}-tiers`} className="flex justify-between items-center">
                    <span className="text-xs">
                        Up to {convertLargeNumberToWords(product?.free_allocation, null)} {product?.type}/mo
                    </span>
                    <span className="font-bold">Free</span>
                </div>
            ) : null}
        </>
    )
}

export function PlanTable({ redirectPath }: { redirectPath: string }): JSX.Element {
    const { billing } = useValues(billingV2Logic)
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)

    const upgradeButtons = billing?.available_plans?.map((plan) => (
        <td key={`${plan.name}-cta`}>
            <LemonButton
                to={`/api/billing-v2/activation?plan=${plan.key}&redirect_path=${redirectPath}`}
                type={plan.name === 'Starter' ? 'secondary' : 'primary'}
                fullWidth
                center
                disableClientSideRouting
                disabled={plan.name === 'Starter' && !billing?.billing_period}
                onClick={() => {
                    if (plan.name != 'Starter') {
                        reportBillingUpgradeClicked(plan.name)
                    }
                }}
            >
                {!billing?.billing_period && plan.name === 'Starter' ? 'Current plan' : 'Upgrade'}
            </LemonButton>
        </td>
    ))

    return !billing?.available_plans?.length ? (
        <Spinner />
    ) : (
        <div className="PlanTable space-x-4">
            <table className="w-full table-fixed">
                <thead>
                    <tr>
                        <td />
                        {billing?.available_plans?.map((plan) => (
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
                            className="PlanTable__th__section bg-muted-light text-muted justify-left rounded text-left mb-2"
                        >
                            <span>Pricing</span>
                        </th>
                    </tr>
                    <tr className="PlanTable__tr__border">
                        <td className="font-bold">Monthly base price</td>
                        {billing?.available_plans?.map((plan) => (
                            <td key={`${plan.name}-basePrice`} className="text-sm font-bold">
                                {getPlanBasePrice(plan)}
                            </td>
                        ))}
                    </tr>
                    {billing?.available_plans
                        ? billing?.available_plans[0].products
                              .filter((product) => product.type !== 'base' && product.type !== 'enterprise')
                              .map((product, i) => (
                                  <tr
                                      key={product.type}
                                      className={
                                          i !== billing?.available_plans?.[0].products.length - 1
                                              ? 'PlanTable__tr__border'
                                              : ''
                                      }
                                  >
                                      <th scope="row">
                                          {product.type === 'events' ? 'Product analytics' : 'Session recording'}
                                          <p className="ml-0 text-xs text-muted mt-1">
                                              Priced per {product.type === 'events' ? 'event' : 'recording'}
                                          </p>
                                      </th>
                                      {billing?.available_plans?.map((plan) => (
                                          <td key={`${plan.key}-${product}`}>{getProductTiers(plan, product.type)}</td>
                                      ))}
                                  </tr>
                              ))
                        : null}
                    <tr>
                        <td />
                        {upgradeButtons}
                    </tr>
                    <tr>
                        <th
                            colSpan={4}
                            className="PlanTable__th__section bg-muted-light text-muted justify-left rounded text-left mb-2"
                        >
                            <span>Features</span>
                        </th>
                    </tr>

                    {billing?.available_plans?.length > 0
                        ? billing.available_plans[billing.available_plans.length - 1].products.map((product) =>
                              product.feature_groups?.map((feature_group) => (
                                  <>
                                      <tr
                                          key={feature_group.name}
                                          className={!feature_group.features.length ? 'PlanTable__tr__border' : ''}
                                      >
                                          <th>{feature_group.name}</th>
                                          {(product.type === 'events' || product.type === 'recordings') &&
                                              billing?.available_plans?.map((plan) => (
                                                  <td key={`${plan.name}-${feature_group.name}`}>
                                                      <PlanIcon
                                                          feature={{
                                                              key: '',
                                                              name: '',
                                                              unit: product.type,
                                                              limit: plan?.products.find((p) => p.type === product.type)
                                                                  ?.free_allocation,
                                                          }}
                                                          timeDenominator="mo"
                                                          className={'text-base'}
                                                      />
                                                  </td>
                                              ))}
                                      </tr>
                                      {feature_group.features.map((feature: BillingV2FeatureType, j: number) => (
                                          <tr
                                              key={feature.name}
                                              className={
                                                  // Show the bottom border on the row if it's the last subfeature in the list
                                                  j === feature_group.features.length - 1 ? 'PlanTable__tr__border' : ''
                                              }
                                          >
                                              <th className="PlanTable__th__subfeature text-muted text-xs">
                                                  <Tooltip title={feature.description}>{feature.name}</Tooltip>
                                              </th>
                                              {billing?.available_plans?.map((plan) => (
                                                  <td key={`${plan.name}-${feature.name}`}>
                                                      {console.log(
                                                          plan?.products
                                                              ?.find((p) => p.type === product.type)
                                                              ?.feature_groups?.find(
                                                                  (fg) => fg.name === feature_group.name
                                                              )
                                                              ?.features?.find((f) => f.key === feature.key),
                                                          'hiiii'
                                                      )}
                                                      <PlanIcon
                                                          feature={plan?.products
                                                              ?.find((p) => p.type === product.type)
                                                              ?.feature_groups?.find(
                                                                  (fg) => fg.name === feature_group.name
                                                              )
                                                              ?.features?.find((f) => f.key === feature.key)}
                                                          className={'text-base'}
                                                      />
                                                  </td>
                                              ))}
                                          </tr>
                                      ))}
                                  </>
                              ))
                          )
                        : null}
                    <tr>
                        <td />
                        {upgradeButtons}
                    </tr>
                </tbody>
            </table>
        </div>
    )
}
