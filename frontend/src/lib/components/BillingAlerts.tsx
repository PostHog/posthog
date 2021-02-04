import React from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { WarningOutlined, ToolFilled } from '@ant-design/icons'
import { Button, Card } from 'antd'
import { billingLogic } from 'scenes/billing/billingLogic'
import { LinkButton } from './LinkButton'

export function BillingAlerts(): JSX.Element {
    const { user } = useValues(userLogic)
    const { alertToShow, percentage, strokeColor } = useValues(billingLogic)

    if (!alertToShow) {
        return <></>
    }

    return (
        <>
            <div style={{ marginTop: 32 }} />
            {alertToShow === 'setup_billing' && (
                <Card>
                    <div style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                            <WarningOutlined className="text-warning" style={{ paddingRight: 8 }} />
                            <b>Action needed!&nbsp;</b>
                            {user?.billing?.plan?.custom_setup_billing_message ||
                                'Please finish setting up your billing information.'}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                            <Button type="primary" href={user?.billing?.subscription_url} icon={<ToolFilled />}>
                                Set up now
                            </Button>
                        </div>
                    </div>
                </Card>
            )}
            {alertToShow === 'usage_near_limit' && (
                <Card>
                    <div style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                            <WarningOutlined className="text-warning" style={{ paddingRight: 16 }} />
                            <div>
                                <b>Warning!</b> The event usage for your organization is nearing its limit. You have
                                already used{' '}
                                <b style={{ color: typeof strokeColor === 'string' ? strokeColor : 'inherit' }}>
                                    {percentage && percentage * 100}%
                                </b>{' '}
                                of your event allocation this month. To avoid losing access to your data,{' '}
                                <b>we recommend upgrading</b> your billing plan now.
                            </div>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', paddingLeft: 16 }}>
                            <LinkButton type="primary" to="/organization/billing">
                                <ToolFilled /> Manage billing
                            </LinkButton>
                        </div>
                    </div>
                </Card>
            )}
        </>
    )
}
