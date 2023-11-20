import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconCheckmark, IconClose, IconWarning } from 'lib/lemon-ui/icons'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { AvailableFeature, BillingProductV2Type, BillingV2FeatureType, BillingV2PlanType } from '~/types'
import { billingLogic } from './billingLogic'
import './PlanTable.scss'

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
    if (plan.is_free) {
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
                                ? // if the base product has a price, then the first tier is included, otherwise it's free
                                  plan.products.filter((p) => p.type === 'base')?.[0]?.unit_amount_usd
                                    ? 'Included'
                                    : 'Free'
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
    const { billing } = useValues(billingLogic)
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)

    const plans = billing?.available_plans?.filter((plan) => plan.name !== 'Enterprise')

    const excludedFeatures: string[] = [AvailableFeature.DASHBOARD_COLLABORATION]

    const upgradeButtons = plans?.map((plan) => (
        <td key={`${plan.name}-cta`}>
            <LemonButton
                to={`/api/billing-v2/activation?plan=${plan.key}&redirect_path=${redirectPath}`}
                type={plan.is_free ? 'secondary' : 'primary'}
                fullWidth
                center
                disableClientSideRouting
                disabled={plan.is_free && !billing?.has_active_subscription}
                onClick={() => {
                    if (!plan.is_free) {
                        reportBillingUpgradeClicked(plan.name)
                    }
                }}
            >
                {!billing?.has_active_subscription && plan.is_free ? 'Current plan' : 'Upgrade'}
            </LemonButton>
        </td>
    ))

    return !plans?.length ? (
        <Spinner />
    ) : (
        <div className="PlanTable space-x-4">
            <table className="w-full table-fixed">
                <thead>
                    <tr>
                        <td />
                        {plans?.map((plan) => (
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
                            colSpan={3}
                            className="PlanTable__th__section bg-side text-muted justify-left rounded text-left mb-2"
                        >
                            <span>Pricing</span>
                        </th>
                    </tr>
                    <tr className="PlanTable__tr__border">
                        <td className="font-bold">Monthly base price</td>
                        {plans?.map((plan) => (
                            <td key={`${plan.name}-basePrice`} className="text-sm font-bold">
                                {getPlanBasePrice(plan)}
                            </td>
                        ))}
                    </tr>
                    {plans
                        ? plans[plans.length - 1].products
                              .filter((product) => product.type !== 'base')
                              .map((product, i) => (
                                  <tr
                                      key={product.type}
                                      className={
                                          plans?.[0].products.length && i !== plans?.[0].products.length - 1
                                              ? 'PlanTable__tr__border'
                                              : ''
                                      }
                                  >
                                      <th scope="row">
                                          {product.name}
                                          <p className="ml-0 text-xs text-muted mt-1">
                                              Priced per {product.type === 'events' ? 'event' : 'recording'}
                                          </p>
                                      </th>
                                      {plans?.map((plan) => (
                                          <td key={`${plan.key}-${product.type}`}>
                                              {getProductTiers(plan, product.type)}
                                          </td>
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
                            colSpan={3}
                            className="PlanTable__th__section bg-side text-muted justify-left rounded text-left mb-2"
                        >
                            <span>Features</span>
                        </th>
                    </tr>

                    {plans?.length > 0
                        ? plans[plans.length - 1].products.map((product) =>
                              product.feature_groups?.map((feature_group) => (
                                  <>
                                      <tr
                                          key={feature_group.name}
                                          className={!feature_group.features.length ? 'PlanTable__tr__border' : ''}
                                      >
                                          <th>{feature_group.name}</th>
                                          {(product.type === 'events' || product.type === 'recordings') &&
                                              plans?.map((plan) => (
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
                                      {feature_group.features.map((feature: BillingV2FeatureType, j: number) => {
                                          return excludedFeatures.includes(feature.key) ? (
                                              <></>
                                          ) : (
                                              <tr
                                                  key={feature.name}
                                                  className={
                                                      // Show the bottom border on the row if it's the last subfeature in the list
                                                      j === feature_group.features.length - 1
                                                          ? 'PlanTable__tr__border'
                                                          : ''
                                                  }
                                              >
                                                  <th className="PlanTable__th__subfeature text-muted text-xs">
                                                      <Tooltip title={feature.description}>{feature.name}</Tooltip>
                                                  </th>
                                                  {plans?.map((plan) => (
                                                      <td key={`${plan.name}-${feature.name}`}>
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
                                          )
                                      })}
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
