import { Alert, Button, Card, InputNumber } from 'antd'
import { useActions, useValues } from 'kea'
import React from 'react'
import defaultImg from 'public/plan-default.svg'
import { ToolOutlined, WarningOutlined } from '@ant-design/icons'
import { billingLogic } from './billingLogic'
import { PlanInterface } from '~/types'

export function CurrentPlan({ plan }: { plan: PlanInterface }): JSX.Element {
    const { billing } = useValues(billingLogic)
    const { setBillingLimit } = useActions(billingLogic)

    return (
        <>
            <div className="space-top" />
            {billing?.should_setup_billing ? (
                <Alert
                    type="warning"
                    message={
                        <>
                            Your plan is <b>currently inactive</b> as you haven't finished setting up your billing
                            information.
                        </>
                    }
                    action={
                        billing.subscription_url && (
                            <Button href={billing.subscription_url} icon={<ToolOutlined />}>
                                Finish setup
                            </Button>
                        )
                    }
                    showIcon
                    icon={<WarningOutlined />}
                />
            ) : (
                <Card title="Organization billing plan">
                    <div style={{ display: 'flex', alignItems: 'center' }}>
                        <div>
                            <img src={plan.image_url || defaultImg} alt="" height={100} width={100} />
                        </div>
                        <div style={{ flexGrow: 1, paddingLeft: 16 }}>
                            <h3 className="l3" style={{ marginBottom: 8 }}>
                                {plan.name}
                            </h3>
                            {/* <Link target="_blank" to={`https://posthog.com/pricing#plan-${plan.key}?${UTM_TAGS}`}>
                                More plan details <IconOpenInNew />
                            </Link> */}
                            <div style={{ marginTop: 4 }}>{plan.price_string}</div>
                            <div style={{ marginTop: 8, marginBottom: 8, alignItems: 'center', display: 'flex' }}>
                                Set monthly billing limit to{' '}
                                <InputNumber
                                    style={{ width: 200, marginLeft: 8, marginRight: 8 }}
                                    onChange={(value): void => {
                                        if (billing) {
                                            setBillingLimit({ ...billing, billing_limit: value })
                                        }
                                    }}
                                    value={billing?.billing_limit || 0}
                                    min={0}
                                    step={10}
                                    // max={100}
                                    addonAfter="$"
                                />{' '}
                                (in US dollars)
                            </div>
                            <div className="text-muted mt">
                                Click on <b>manage subscription</b> to cancel your billing agreement,{' '}
                                <b>update your card</b> or other billing information,
                            </div>
                        </div>
                        <div>
                            <Button type="primary" href="/billing/manage" icon={<ToolOutlined />}>
                                Manage subscription
                            </Button>
                            <div className="text-muted text-center">Get past invoices too</div>
                        </div>
                    </div>
                </Card>
            )}
        </>
    )
}
