import { Card, Progress, Tooltip } from 'antd'
import { useValues } from 'kea'
import { compactNumber } from 'lib/utils'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
import { billingLogic } from './billingLogic'

export function CurrentUsage(): JSX.Element {
    const { eventAllocation, percentage, strokeColor } = useValues(billingLogic)
    const { user } = useValues(userLogic)
    const plan = user?.billing?.plan

    // :TODO: Temporary support for legacy `FormattedNumber` type
    const current_usage =
        typeof user?.billing?.current_usage === 'number'
            ? user.billing.current_usage
            : user?.billing?.current_usage?.value
    const allocation = typeof eventAllocation === 'number' ? eventAllocation : eventAllocation?.value

    return (
        <>
            <div className="space-top" />
            <Card title="Current monthly usage">
                {current_usage !== undefined ? (
                    <>
                        Your organization has used{' '}
                        <Tooltip title={`${current_usage.toLocaleString()} events`}>
                            <b>{compactNumber(current_usage)}</b>
                        </Tooltip>{' '}
                        events this month.{' '}
                        {allocation && (
                            <>
                                You can use up to <b>{compactNumber(allocation)}</b> events per month.
                            </>
                        )}
                        {plan &&
                            !plan.allowance && // :TODO: DEPRECATED
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
                        Currently we do not have information about your usage. Please check back again in a few minutes
                        or{' '}
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
