import { Progress } from 'antd'
import { useActions, useValues } from 'kea'
import { compactNumber } from 'lib/utils'
import { billingLogic } from './billingLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { BillingTierType } from '~/types'
import { dayjs } from 'lib/dayjs'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { useState } from 'react'

export function CurrentUsage(): JSX.Element | null {
    const { eventAllocation, percentage, strokeColor, showUsageTiers, billing } = useValues(billingLogic)
    const { toggleUsageTiers, setBillingLimit } = useActions(billingLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [billingLimitValue, setbillingLimitValue] = useState(billing?.billing_limit || 0)
    const plan = billing?.plan

    if (!billing) {
        return null
    }

    const columns: LemonTableColumns<BillingTierType> = [
        {
            title: 'Tier',
            dataIndex: 'name',
        },
        {
            title: 'Price per event',
            render: function Render(_, billingTier: BillingTierType): JSX.Element {
                return <div>${billingTier.price_per_event}</div>
            },
        },
        {
            title: 'Number of events',
            dataIndex: 'number_of_events',
        },
        {
            title: 'Sub-total',
            render: function Render(_, billingTier: BillingTierType): JSX.Element {
                return <div>${billingTier.subtotal}</div>
            },
        },
        {
            title: 'Running total',
            render: function Render(_, billingTier: BillingTierType): JSX.Element {
                return <div>${billingTier.running_total}</div>
            },
        },
    ]

    const usage = billing.current_bill_usage || billing.current_usage

    const showBillingLimit = featureFlags[FEATURE_FLAGS.BILLING_LIMIT]

    return (
        <div className="border rounded p-4">
            {billing.should_display_current_bill && (
                <>
                    <h3 className="text-xs uppercase font-semibold text-muted">Current Bill Amount</h3>
                    {billing?.current_bill_amount !== undefined && billing?.current_bill_amount !== null ? (
                        <div className="flex flex-col space-y-2">
                            <div className="text-5xl font-extrabold">{`$${billing?.current_bill_amount?.toLocaleString()}`}</div>
                            <p>
                                This is the amount (in dollars) of the bill for the currently ongoing period. The final
                                amount will be billed a few days after the end of the month. Please note this number is
                                reported on a daily basis,{' '}
                                <b>so events ingested in the last 24 hours may not be reflected yet.</b>
                            </p>
                            {showUsageTiers && <LemonTable columns={columns} dataSource={billing.tiers || []} />}
                            <div className="flex-none">
                                <LemonButton type="secondary" onClick={toggleUsageTiers}>
                                    {showUsageTiers ? 'Hide' : 'Show'} usage tiers
                                </LemonButton>
                            </div>
                        </div>
                    ) : (
                        <>
                            We can't show your current bill amount right now. Please check back again in a few minutes
                            or{' '}
                            <a href="https://posthog.com/support/" target="_blank">
                                contact us
                            </a>{' '}
                            if this message does not disappear.
                        </>
                    )}
                    {billing?.current_bill_cycle && (
                        <p className="mt-4 text-muted">
                            Your current billing period runs from{' '}
                            <strong>
                                {dayjs.unix(billing.current_bill_cycle.current_period_start).format('MMMM DD, YYYY')}
                            </strong>{' '}
                            until{' '}
                            <strong>
                                {dayjs.unix(billing.current_bill_cycle.current_period_end).format('MMMM DD, YYYY')}
                            </strong>
                            , which is when you'll be charged.
                        </p>
                    )}
                    <LemonDivider className="my-6" />
                </>
            )}
            <h3 className="text-xs uppercase font-semibold text-muted">Current Usage</h3>
            {usage !== null ? (
                <>
                    Your organization has used{' '}
                    <Tooltip title={`${usage.toLocaleString()} events`}>
                        <b>{compactNumber(usage)}</b>
                    </Tooltip>{' '}
                    events {billing.current_bill_usage ? 'this billing period' : 'this month'} (calculated every day).{' '}
                    {eventAllocation && (
                        <>
                            You can use up to <b>{compactNumber(eventAllocation)}</b> events per month.
                        </>
                    )}
                    {plan &&
                        !plan.event_allowance &&
                        !plan.is_metered_billing &&
                        'Your current plan has an unlimited event allocation.'}
                    <Progress
                        type="line"
                        percent={percentage !== null ? Math.floor(percentage * 100) : 100}
                        strokeColor={strokeColor}
                        status={percentage !== null ? 'normal' : 'success'}
                    />
                    <p>
                        This is the number of events that your organization has ingested across all your projects for
                        the current month and that will be billed a few days after the end of the month.
                    </p>
                </>
            ) : (
                <div>
                    Currently we do not have information about the number of billed events. Please check back again in a
                    few minutes or{' '}
                    <a href="https://posthog.com/support/" target="_blank">
                        contact us
                    </a>{' '}
                    if this message does not disappear.
                </div>
            )}

            {showBillingLimit && billing.plan && (
                <>
                    <LemonDivider className="my-6" />
                    <h3 className="text-xs uppercase font-semibold text-muted">Billing Limit</h3>
                    <div className="flex flex-row space-x-2 my-2">
                        <div className="flex-none">
                            <LemonInput
                                type="number"
                                onChange={(value): void => {
                                    setbillingLimitValue(value || 0)
                                }}
                                value={billingLimitValue}
                                min={0}
                                step={10}
                                prefix={<>$</>}
                                suffix={<div className="shrink-0">USD / MONTH</div>}
                            />
                        </div>
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                if (billing) {
                                    setBillingLimit({ ...billing, billing_limit: billingLimitValue })
                                }
                            }}
                        >
                            Submit
                        </LemonButton>
                    </div>
                    <p>
                        Set a billing limit to control your recurring costs.{' '}
                        <b>Your critical data will still be ingested and available in the product.</b> Some features may
                        cease operation if your usage greatly exceeds your billing cap.
                    </p>
                </>
            )}
        </div>
    )
}
