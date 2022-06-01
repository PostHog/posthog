import { Card, Progress } from 'antd'
import { useValues } from 'kea'
import { compactNumber } from 'lib/utils'
import React from 'react'
import { billingLogic } from './billingLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { BillingTierType } from '~/types'
import { dayjs } from 'lib/dayjs'

export function CurrentUsage(): JSX.Element | null {
    const { eventAllocation, percentage, strokeColor, billing } = useValues(billingLogic)
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

    return (
        <>
            <div className="space-top" />
            <Card title="Current monthly usage">
                {billing.should_display_current_bill && (
                    <>
                        <h3 className="l3">Current bill amount</h3>
                        {billing?.current_bill_amount !== undefined && billing?.current_bill_amount !== null ? (
                            <>
                                This is the amount (in dollars) of the bill for the currently ongoing period. The final
                                amount will be billed a few days after the end of the month. Please note this number is
                                reported on a daily basis,{' '}
                                <b>so events ingested in the last 24 hours may not be reflected yet.</b>
                                <div className="bill-amount">
                                    {`$${billing?.current_bill_amount?.toLocaleString()}`}
                                </div>
                                <LemonTable columns={columns} dataSource={billing.tiers || []} />
                            </>
                        ) : (
                            <>
                                We can't show your current bill amount right now. Please check back again in a few
                                minutes or{' '}
                                <a href="https://posthog.com/support/" target="_blank">
                                    contact us
                                </a>{' '}
                                if this message does not disappear.
                            </>
                        )}
                    </>
                )}
                <h3 className="l3 mt">Current event usage</h3>
                {usage !== null ? (
                    <>
                        Your organization has used{' '}
                        <Tooltip title={`${usage.toLocaleString()} events`}>
                            <b>{compactNumber(usage)}</b>
                        </Tooltip>{' '}
                        events {billing.current_bill_usage ? 'this billing period' : 'this month'} (calculated every
                        day).{' '}
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
                    </>
                ) : (
                    <div>
                        Currently we do not have information about the number of billed events. Please check back again
                        in a few minutes or{' '}
                        <a href="https://posthog.com/support/" target="_blank">
                            contact us
                        </a>{' '}
                        if this message does not disappear.
                    </div>
                )}
                {billing?.current_bill_cycle && (
                    <div className="mt text-muted">
                        Your current billing period runs from{' '}
                        <strong>
                            {dayjs.unix(billing.current_bill_cycle.current_period_start).format('MMMM DD, YYYY')}
                        </strong>{' '}
                        until{' '}
                        <strong>
                            {dayjs.unix(billing.current_bill_cycle.current_period_end).format('MMMM DD, YYYY')}
                        </strong>
                        , which is when you'll be charged.
                    </div>
                )}
            </Card>
        </>
    )
}
