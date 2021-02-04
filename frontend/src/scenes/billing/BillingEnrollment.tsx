import { Button, Card, Col, Row, Skeleton, Spin } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import { PlanInterface } from '~/types'
import { billingLogic } from './billingLogic'
import defaultImg from 'public/plan-default.svg'

function Plan({ plan, onSubscribe }: { plan: PlanInterface; onSubscribe: (plan: PlanInterface) => void }): JSX.Element {
    return (
        <Card>
            <img src={plan.image_url || defaultImg} alt="" height={100} width={100} />
            <h3 style={{ fontSize: 22 }}>{plan.name}</h3>
            <div>
                <Button
                    data-attr="btn-subscribe-now"
                    data-plan={plan.key}
                    type="primary"
                    onClick={() => onSubscribe(plan)}
                >
                    Subscribe now
                </Button>
            </div>
        </Card>
    )
}

export function BillingEnrollment(): JSX.Element {
    const { plans, plansLoading, billingSubscriptionLoading } = useValues(billingLogic)
    const { subscribe } = useActions(billingLogic)

    const handleBillingSubscribe = (plan: PlanInterface): void => {
        subscribe(plan.key)
    }

    if (!plans.length && !plansLoading) {
        // If there are no plans to which enrollment is available, no point in showing the component
        return <></>
    }

    return (
        <>
            <div className="space-top" />
            {plansLoading ? (
                <Card>
                    <Skeleton active />
                </Card>
            ) : (
                <Card title="Billing Plan Enrollment">
                    <Row gutter={16} className="space-top" style={{ display: 'flex', justifyContent: 'center' }}>
                        {plans.map((plan: PlanInterface) => (
                            <Col sm={8} key={plan.key} className="text-center">
                                {billingSubscriptionLoading ? (
                                    <Spin>
                                        <Plan plan={plan} onSubscribe={handleBillingSubscribe} />
                                    </Spin>
                                ) : (
                                    <Plan plan={plan} onSubscribe={handleBillingSubscribe} />
                                )}
                            </Col>
                        ))}
                    </Row>
                </Card>
            )}
        </>
    )
}
