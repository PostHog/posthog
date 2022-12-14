import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconArrowRight, IconCheckmark, IconClose, IconWarning } from 'lib/components/icons'
import { LemonSnack } from 'lib/components/LemonSnack/LemonSnack'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingTestLogic } from './billingTestLogic'
import { BillingPlan } from '~/types'
import './PlanTable.scss'

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

export function PlanTable({ redirectPath, plans }: { redirectPath: string; plans: BillingPlan[] }): JSX.Element {
    const { billing } = useValues(billingTestLogic)
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    console.log(plans, 'THE PLANS')

    const upgradeButtons = plans.map((plan) => (
        <td key={`${plan.key}-cta`}>
            <LemonButton
                to={`${plan.signup_link}&redirect_path=${redirectPath}`}
                type={plan.key === 'free' ? 'secondary' : 'primary'}
                fullWidth
                center
                disableClientSideRouting
                disabled={plan.key === 'free' && !billing?.billing_period}
                onClick={() => {
                    if (plan.key != 'free') {
                        reportBillingUpgradeClicked(plan.name)
                    }
                }}
            >
                {!billing?.billing_period && plan.name === 'free' ? 'Current plan' : 'Upgrade'}
            </LemonButton>
        </td>
    ))

    console.log(plans, 'THE PLANS')

    return (
        <div className="PlanTable space-x-4">
            <table className="w-full table-fixed">
                <thead>
                    <tr>
                        <td />
                        {plans.map((plan) => (
                            <td key={`plan-name-${plan.name}`}>
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
                        {plans.map((plan) => (
                            <td key={`${plan.name}-basePrice`} className="text-sm font-bold">
                                {/* {plan.basePrice} */}
                                ADD BASE PRICE
                            </td>
                        ))}
                    </tr>
                    {Object.keys(plans[0].feature_list).map((product, i) => (
                        <tr
                            key={`plan-pricing-${product}`}
                            className={
                                i !== Object.keys(plans[0].feature_list).length - 1 ? 'PlanTable__tr__border' : ''
                            }
                        >
                            <th scope="row">
                                {plans[0].feature_list[product].description}
                                <p className="ml-0 text-xs text-muted mt-1">
                                    {plans[0].feature_list[product].note || 'ADD NOTES'}
                                </p>
                            </th>
                            {plans.map((plan) => (
                                <td key={`plan-tiers-${plan.name}-${product}`}>
                                    ADD PRICING TIERS
                                    {/* {plan.feature_list[i].tiers.map((tier) => (
                                        <div
                                            key={`${plan.name}-${product}-${tier.description}`}
                                            className="flex justify-between items-center"
                                        >
                                            <span className="text-xs">{tier.description}</span>
                                            <span className="font-bold">{tier.price}</span>
                                        </div>
                                    ))} */}
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
                    {Object.keys(plans[0].feature_list).map((feature, i) => (
                        <>
                            <tr
                                key={`plan-product-features-${feature}`}
                                className={
                                    // Show the bottom border if it's not the last feature in the list and it doesn't have subfeatures
                                    i !== Object.keys(plans[0].feature_list).length - 1 &&
                                    !plans[0].feature_list[feature].features
                                        ? 'PlanTable__tr__border'
                                        : ''
                                }
                            >
                                <th>{plans[0].feature_list[feature].description}</th>
                                {plans.map((plan) => (
                                    <td key={`plan-product-features-2-${plan.name}-${feature}`}>
                                        <PlanIcon
                                            value={plan.feature_list[feature].value}
                                            note={plan.feature_list[feature].description}
                                            className={'text-xl'}
                                        />
                                        CALCULATE FROM SUBFEATURES
                                    </td>
                                ))}
                            </tr>
                            {plans[0].feature_list[feature].features
                                ? Object.keys(plans[0].feature_list[feature].features).map((subfeature, j) => (
                                      <tr
                                          key={subfeature}
                                          className={
                                              // Show the bottom border on the row if it's the last subfeature in the list
                                              j === Object.keys(plans[0].feature_list[feature].features).length - 1
                                                  ? 'PlanTable__tr__border'
                                                  : ''
                                          }
                                      >
                                          <th className="PlanTable__th__subfeature text-muted text-xs">
                                              {plans[0].feature_list[feature].features[subfeature].description}
                                          </th>
                                          {plans.map((plan) => (
                                              <td key={`${plan.name}-${subfeature}`}>
                                                  <PlanIcon
                                                      value={plan.feature_list[feature].features[subfeature]?.value}
                                                      note={
                                                          plan.feature_list[feature].features[subfeature]?.description
                                                      }
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
