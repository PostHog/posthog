import React from 'react'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { WarningOutlined, ToolFilled } from '@ant-design/icons'
import { Button, Card } from 'antd'

export function BillingToolbar(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <>
            {user?.billing?.should_setup_billing && user?.billing.subscription_url && (
                <Card>
                    <div style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                            <WarningOutlined className="text-warning" style={{ paddingRight: 8 }} />
                            {user?.billing?.plan?.custom_setup_billing_message ||
                                'Please set up your billing information'}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                            <Button type="primary" href={user.billing.subscription_url} icon={<ToolFilled />}>
                                Set up now
                            </Button>
                        </div>
                    </div>
                </Card>
            )}
        </>
    )
}
