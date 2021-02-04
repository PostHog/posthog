import { Card, Progress, Tooltip } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
import { billingLogic } from './billingLogic'

export function CurrentUsage(): JSX.Element {
    const { percentage, strokeColor } = useValues(billingLogic)
    const { user } = useValues(userLogic)
    const plan = user?.billing?.plan

    return (
        <>
            <div className="space-top" />
            <Card title="Current monthly usage">
                {user?.billing?.current_usage && (
                    <>
                        Your organization has used{' '}
                        <Tooltip title={`${user.billing.current_usage.value.toLocaleString()} events`}>
                            <b>{user.billing.current_usage.formatted}</b>
                        </Tooltip>{' '}
                        events this month.{' '}
                        {plan?.allowance && (
                            <>
                                Your current plan has an allowance of up to <b>{plan.allowance.formatted}</b> events per
                                month.
                            </>
                        )}
                        {plan && !plan.allowance && !plan.is_metered_billing && (
                            <>Your current plan has an unlimited event allowance.</>
                        )}
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
                )}
                {!user?.billing?.current_usage && (
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
