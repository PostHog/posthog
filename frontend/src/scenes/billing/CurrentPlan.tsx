import { Alert, Button, Card } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { userLogic } from 'scenes/userLogic'
import defaultImg from 'public/plan-default.svg'
import { Link } from 'lib/components/Link'
import { IconExternalLink } from 'lib/components/icons'
import { ToolOutlined, WarningOutlined } from '@ant-design/icons'
import { UTM_TAGS } from './billingLogic'
import { PlanInterface } from '~/types'

export function CurrentPlan({ plan }: { plan: PlanInterface }): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <>
            <div className="space-top" />
            {user?.billing?.should_setup_billing ? (
                <Alert
                    type="warning"
                    message={
                        <>
                            Your plan is <b>currently inactive</b> as you haven't finished setting up your billing
                            information.
                        </>
                    }
                    action={
                        user.billing.subscription_url && (
                            <Button href={user.billing.subscription_url} icon={<ToolOutlined />}>
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
                            <Link target="_blank" to={`https://posthog.com/pricing#plan-${plan.key}?${UTM_TAGS}`}>
                                More plan details <IconExternalLink />
                            </Link>
                            <div style={{ marginTop: 4 }}>{plan.price_string}</div>
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
