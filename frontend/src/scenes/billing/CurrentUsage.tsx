import { Card, Progress, Tooltip } from 'antd'
import { useValues } from 'kea'
import { compactNumber } from 'lib/utils'
import React from 'react'
import { billingLogic } from './billingLogic'
import { InfoCircleOutlined } from '@ant-design/icons'

export function CurrentUsage(): JSX.Element | null {
    const { eventAllocation, percentage, strokeColor, billing } = useValues(billingLogic)
    const plan = billing?.plan

    if (!billing) {
        return null
    }

    return (
        <>
            <div className="space-top" />
            <Card title="Current monthly usage">
                {billing.should_display_current_bill && (
                    <>
                        <h3 className="l3">Current bill amount</h3>
                        This is the amount (in dollars) of the bill for the currently ongoing period. The final amount
                        will be billed a few days after the end of the month.{' '}
                        <b>
                            Please note this number is computed daily, so events ingested in the last 24 hours may not
                            be reflected yet.
                        </b>{' '}
                        Keep in mind if you're trying to compare number of events and bill amount.
                        <div className="bill-amount">
                            {billing?.current_bill_amount !== undefined && billing?.current_bill_amount !== null ? (
                                `$${billing?.current_bill_amount?.toLocaleString()}`
                            ) : (
                                <>
                                    Unavailable{' '}
                                    <Tooltip title="We can't show your current bill amount right now. If you keep seeing this message, contact us.">
                                        <InfoCircleOutlined />
                                    </Tooltip>
                                </>
                            )}
                        </div>
                    </>
                )}
                <h3 className="l3 mt">Current event usage</h3>
                {billing.current_usage !== null ? (
                    <>
                        Your organization has used{' '}
                        <Tooltip title={`${billing.current_usage.toLocaleString()} events`}>
                            <b>{compactNumber(billing.current_usage)}</b>
                        </Tooltip>{' '}
                        events this month (calculated roughly every hour).{' '}
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
                            percent={percentage !== null ? percentage * 100 : 100}
                            strokeColor={strokeColor}
                            status={percentage !== null ? 'normal' : 'success'}
                        />
                        {plan?.is_metered_billing && (
                            <div className="mt text-muted">
                                This is the number of events that your organization has ingested across all your
                                projects for the <b>current month</b> and that <b>will be billed</b> a few days after
                                the end of the month.
                            </div>
                        )}
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
            </Card>
        </>
    )
}
