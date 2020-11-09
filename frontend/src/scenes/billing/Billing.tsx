import React from 'react'
import { useValues, useActions } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { billingLogic } from './billingLogic'
import { Card, Progress, Row, Col, Button, Popconfirm, Spin } from 'antd'
import defaultImg from 'public/plan-default.svg'
import { PlanInterface } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'

function Plan({ plan, onUpgrade }: { plan: PlanInterface; onUpgrade: (plan: PlanInterface) => void }): JSX.Element {
    return (
        <Card>
            <img src={plan.image_url || defaultImg} alt="" height={100} width={100} />
            <h3 style={{ fontSize: 22 }}>{plan.name}</h3>
            <div>
                <Popconfirm
                    title={`Sign up for the ${plan.name} now? You will need a bank card.`}
                    onConfirm={() => onUpgrade(plan)}
                    okText="Yes"
                    cancelText="No"
                >
                    <Button data-attr="btn-upgrade-now" data-plan={plan.key}>
                        Upgrade now
                    </Button>
                </Popconfirm>
            </div>
        </Card>
    )
}

export function Billing(): JSX.Element {
    const { plans, billingSubscriptionLoading, percentage, strokeColor } = useValues(billingLogic)
    const { subscribe } = useActions(billingLogic)
    const { user } = useValues(userLogic)

    const handleBillingSubscribe = (plan: PlanInterface): void => {
        subscribe(plan.key)
    }

    return (
        <>
            <PageHeader
                title={
                    <>
                        Billing &amp; usage information <span style={{ fontSize: 12, color: '#F7A501' }}>BETA</span>
                    </>
                }
            />
            <div className="space-top" />
            <Card title="Current usage">
                {user?.billing?.current_usage && (
                    <>
                        Your organization has used <b>{user.billing.current_usage.formatted}</b> events this month.{' '}
                        {user?.billing.plan?.allowance && (
                            <>
                                Your current plan has an allowance of up to{' '}
                                <b>{user?.billing.plan.allowance.formatted}</b> events per month.
                            </>
                        )}
                        {user?.billing.plan && !user?.billing.plan.allowance && (
                            <>Your current plan has an unlimited event allowance.</>
                        )}
                        <Progress
                            type="line"
                            percent={percentage !== null ? percentage * 100 : 100}
                            strokeColor={strokeColor}
                            status={percentage !== null ? 'normal' : 'success'}
                        />
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
            <Card title="Billing plan">
                {user?.billing.plan && !user?.billing.should_setup_billing && (
                    <>
                        Your organization is currently on the <b>{user.billing.plan.name}</b>. We're working on allowing
                        self-serve billing management, in the meantime, please{' '}
                        <a href="mailto:hey@posthog.com?subject=Billing%20management">contact us</a> if you wish to
                        change or cancel your subscription.
                    </>
                )}
                {user?.billing.plan && user?.billing.should_setup_billing && (
                    <>
                        Your organization is currently enrolled in the <b>{user?.billing.plan.name}</b>, but billing
                        details have not been set up. Please{' '}
                        <a href={user?.billing.subscription_url}>set them up now</a> or change your plan.{' '}
                    </>
                )}
                {!user?.billing.plan && <>Your organization does not have a billing plan set up yet.</>}
                {plans?.length > 0 && (
                    <>
                        Choose a plan from the list below to initiate a subscription.{' '}
                        <b>
                            For more information on our plans, check out our{' '}
                            <a href="https://posthog.com/pricing" target="_blank">
                                pricing page
                            </a>
                            .
                        </b>
                        <Row gutter={16} className="space-top">
                            {plans.map((plan: PlanInterface) => (
                                <Col sm={24 / plans.length} key={plan.key} className="text-center">
                                    {billingSubscriptionLoading && (
                                        <Spin>
                                            <Plan plan={plan} onUpgrade={handleBillingSubscribe} />
                                        </Spin>
                                    )}
                                    {!billingSubscriptionLoading && (
                                        <Plan plan={plan} onUpgrade={handleBillingSubscribe} />
                                    )}
                                </Col>
                            ))}
                        </Row>
                    </>
                )}
            </Card>
            <div style={{ marginBottom: 128 }} />
        </>
    )
}
