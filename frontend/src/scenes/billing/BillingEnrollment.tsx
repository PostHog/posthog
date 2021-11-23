import { Button, Card, Col, Row, Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import React, { useEffect, useState } from 'react'
import { PlanInterface } from '~/types'
import { billingLogic } from './billingLogic'
import defaultImg from 'public/plan-default.svg'
import { Spinner } from 'lib/components/Spinner/Spinner'

function Plan({ plan, onSubscribe }: { plan: PlanInterface; onSubscribe: (plan: PlanInterface) => void }): JSX.Element {
    const [detail, setDetail] = useState('')
    const [isDetailLoading, setIsDetailLoading] = useState(true)

    const loadPlanDetail = async (key: string): Promise<void> => {
        const response = await fetch(`/api/plans/${key}/template/`)
        if (response.ok) {
            setDetail(await response.text())
        }
        setIsDetailLoading(false)
    }

    useEffect(() => {
        loadPlanDetail(plan.key)
    }, [plan.key])

    return (
        <Card>
            <div className="cursor-pointer" onClick={() => onSubscribe(plan)}>
                <img src={plan.image_url || defaultImg} alt="" height={100} width={100} />
                <h3 style={{ fontSize: 22 }}>{plan.name}</h3>
                <div style={{ fontWeight: 'bold', marginBottom: 16, fontSize: 16 }}>{plan.price_string}</div>
            </div>
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
            {isDetailLoading ? (
                <Skeleton paragraph={{ rows: 6 }} title={false} className="mt" active />
            ) : (
                <div className="plan-description" dangerouslySetInnerHTML={{ __html: detail }} />
            )}
        </Card>
    )
}

export function BillingEnrollment(): JSX.Element | null {
    const { plans, plansLoading, billingSubscriptionLoading } = useValues(billingLogic)
    const { subscribe } = useActions(billingLogic)

    const handleBillingSubscribe = (plan: PlanInterface): void => {
        subscribe(plan.key)
    }

    if (!plans.length && !plansLoading) {
        // If there are no plans to which enrollment is available, no point in showing the component
        return null
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
                                    <Spinner />
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
