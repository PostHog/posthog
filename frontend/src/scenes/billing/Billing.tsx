import React from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { billingLogic } from './billingLogic'
import { Card, Progress, Button, Tooltip } from 'antd'
import defaultImg from 'public/plan-default.svg'
import { PageHeader } from 'lib/components/PageHeader'
import { Link } from 'lib/components/Link'
import { IconExternalLink } from 'lib/components/icons'
import { ToolOutlined } from '@ant-design/icons'

const UTM_TAGS = 'utm_medium=in-product&utm_campaign=billing-management'

export function Billing(): JSX.Element {
    const { percentage, strokeColor } = useValues(billingLogic)
    const { user } = useValues(userLogic)
    const plan = user?.billing?.plan

    return (
        <>
            <PageHeader title="Billing &amp; usage information" />
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
            <div className="space-top" />
            {plan && !user?.billing?.should_setup_billing && (
                <Card title="Organization billing plan">
                    <div style={{ display: 'flex', alignItems: 'center' }}>
                        <div>
                            <img src={plan.image_url || defaultImg} alt="" height={100} width={100} />
                        </div>
                        <div style={{ flexGrow: 1, paddingLeft: 16 }}>
                            <h3 className="l3" style={{ marginBottom: 8 }}>
                                {plan.name}
                            </h3>
                            <Link target="_blank" to={`https://posthog.com/pricing#plan-${plan.key}?${UTM_TAGS}`}>
                                More plan details <IconExternalLink />
                            </Link>
                            <div style={{ marginTop: 4 }}>
                                $0.000225/event per month - First 10,000 events every month for free
                            </div>
                            <div className="text-muted mt">
                                To change or cancel your billing agreement click on <b>manage subscription</b>.
                            </div>
                        </div>
                        <div>
                            <Button type="primary" href="/billing/manage" icon={<ToolOutlined />}>
                                Manage subscription
                            </Button>
                        </div>
                    </div>
                </Card>
            )}
            <div style={{ marginBottom: 128 }} />
        </>
    )
}
