import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { humanFriendlyCurrency } from 'lib/utils'

import { StripePortalButton } from './StripePortalButton'
import { billingLogic } from './billingLogic'

export const BillingSummary = (): JSX.Element => {
    const { billing } = useValues(billingLogic)

    return (
        <div className="flex w-fit flex-wrap gap-6">
            <div className="flex-1 pt-2">
                <div className="deprecated-space-y-4">
                    {billing?.has_active_subscription && billing.billing_period && (
                        <>
                            <div className="flex flex-row flex-wrap items-end gap-x-10 gap-y-4">
                                <div>
                                    <LemonLabel
                                        info={`This is the current amount you have been billed for this ${billing.billing_period.interval} so far. This number updates once daily.`}
                                    >
                                        Current bill total
                                    </LemonLabel>
                                    <div className="text-6xl font-bold">
                                        {billing.discount_percent
                                            ? // if they have a discount percent, we want to show the amount they are due - so the total after discount
                                              humanFriendlyCurrency(billing.current_total_amount_usd_after_discount)
                                            : // but if they have credits, we want to show the amount they are due before credits,
                                              // so they know what their total deduction will be
                                              // We don't let people have credits and discounts at the same time
                                              humanFriendlyCurrency(billing.current_total_amount_usd)}
                                    </div>
                                </div>
                                {billing.projected_total_amount_usd &&
                                    parseFloat(billing.projected_total_amount_usd) > 0 && (
                                        <div>
                                            <LemonLabel
                                                info={`This is roughly calculated based on your current bill${
                                                    billing?.discount_percent ? ', discounts on your account,' : ''
                                                } and the remaining time left in this billing period. This number updates once daily. ${
                                                    billing.projected_total_amount_usd_with_limit !==
                                                    billing.projected_total_amount_usd
                                                        ? ` This value is capped at your current billing limit, we will never charge you more than your billing limit. If you did not have a billing limit set then your projected total would be ${humanFriendlyCurrency(
                                                              parseFloat(billing.projected_total_amount_usd || '0')
                                                          )}`
                                                        : ''
                                                }`}
                                                className="text-secondary"
                                            >
                                                Projected total
                                            </LemonLabel>
                                            <div className="text-secondary text-2xl font-semibold">
                                                {billing.discount_percent
                                                    ? humanFriendlyCurrency(
                                                          billing.projected_total_amount_usd_with_limit_after_discount
                                                      )
                                                    : humanFriendlyCurrency(
                                                          billing.projected_total_amount_usd_with_limit
                                                      )}
                                            </div>
                                        </div>
                                    )}
                                {billing.discount_amount_usd && (
                                    <div>
                                        <LemonLabel
                                            info={`The total credits remaining in your account.${
                                                billing.amount_off_expires_at
                                                    ? ' Your credits expire on ' +
                                                      billing.amount_off_expires_at.format('LL')
                                                    : ''
                                            }`}
                                            className="text-secondary"
                                        >
                                            Available credits
                                        </LemonLabel>
                                        <div className="text-secondary text-2xl font-semibold">
                                            {humanFriendlyCurrency(billing.discount_amount_usd, 0)}
                                        </div>
                                    </div>
                                )}
                                {billing.discount_percent && (
                                    <div>
                                        <LemonLabel
                                            info="The discount applied to your current bill, reflected in the total amount."
                                            className="text-secondary"
                                        >
                                            Applied discount
                                        </LemonLabel>
                                        <div className="text-secondary text-2xl font-semibold">
                                            {billing.discount_percent}%
                                        </div>
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                    {billing?.billing_period && (
                        <div>
                            <p className="mb-0 ml-0 break-words">
                                {billing?.has_active_subscription ? 'Billing period' : 'Cycle'}:{' '}
                                <b className="whitespace-nowrap">
                                    {billing.billing_period.current_period_start.format('LL')}
                                </b>{' '}
                                to{' '}
                                <b className="whitespace-nowrap">
                                    {billing.billing_period.current_period_end.format('LL')}
                                </b>{' '}
                                ({billing.billing_period.current_period_end.diff(dayjs(), 'days')} days remaining)
                            </p>
                            {!billing.has_active_subscription && (
                                <p className="text-secondary mb-0 ml-0 break-words italic">
                                    Monthly free allocation resets at the end of the cycle.
                                </p>
                            )}
                        </div>
                    )}
                </div>
                <StripePortalButton />
            </div>
        </div>
    )
}
