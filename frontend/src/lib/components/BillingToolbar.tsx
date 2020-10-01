import React from 'react'
import { WarningOutlined, ToolFilled } from '@ant-design/icons'
import { Button } from 'antd'

export function BillingToolbar({
    billingUrl = null,
    message,
}: {
    billingUrl: string | null
    message: string
}): JSX.Element {
    return (
        <>
            {billingUrl && (
                <div className="card">
                    <div className="card-body" style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                            <WarningOutlined className="text-warning" style={{ paddingRight: 8 }} />
                            {message || 'Please set up your billing information'}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center' }}>
                            <Button type="primary" href={billingUrl} icon={<ToolFilled />}>
                                Set up now
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </>
    )
}
