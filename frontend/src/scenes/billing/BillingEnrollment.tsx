import { Button, Card, Col, Row, Skeleton } from 'antd'
import { dayjs } from 'lib/dayjs'
import { useActions, useValues } from 'kea'
import React, { useEffect, useState } from 'react'
import { PlanInterface } from '~/types'
import { billingLogic } from './billingLogic'
import defaultImg from 'public/plan-default.svg'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { LemonButton } from '@posthog/lemon-ui'

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
            <div style={{ display: 'flex', justifyContent: 'center' }}>
                <LemonButton
                    data-attr="btn-subscribe-now"
                    data-plan={plan.key}
                    type="primary"
                    onClick={() => onSubscribe(plan)}
                >
                    Subscribe now
                </LemonButton>
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
    const { plans, plansLoading, billingSubscriptionLoading, billing } = useValues(billingLogic)
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
                    {billing.free_trial_until && (
                        <>
                            {dayjs().isBefore(billing.free_trial_until) && (
                                <>
                                    You have <strong>{dayjs(billing.free_trial_until).fromNow(true)}</strong> left of
                                    your free trial.{' '}
                                    <Button
                                        style={{ padding: 0 }}
                                        type="link"
                                        onClick={() => handleBillingSubscribe(plans[0])}
                                    >
                                        Subscribe now
                                    </Button>{' '}
                                    to make sure you don't lose access to any features. We will only start charging you
                                    after your trial period ends.{' '}
                                </>
                            )}
                            {dayjs().isAfter(billing.free_trial_until) && (
                                <>Your free trial has expired. Subscribe to keep access to all features. </>
                            )}
                            <br />
                            <br />
                        </>
                    )}
                    <Row gutter={8} className="space-top" style={{ display: 'flex', justifyContent: 'center' }}>
                        {plans.map((plan: PlanInterface) => (
                            <Col sm={12} key={plan.key} className="text-center">
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
