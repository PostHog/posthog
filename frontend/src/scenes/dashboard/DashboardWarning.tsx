import React from 'react'
import { useValues } from 'kea'
import { Alert } from 'antd'
import { WarningOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'

export function DashboardWarning({ canEditDashboard }: { canEditDashboard: boolean }): JSX.Element | null {
    const { user } = useValues(userLogic)

    if (canEditDashboard) {
        return null
    }

    return (
        <>
            <Alert
                type="warning"
                message={`Hello there, ${user?.name}`}
                className="demo-warning"
                description={<span>Only the dashboard creator is allowed to edit the dashboard.</span>}
                icon={<WarningOutlined />}
                showIcon
                closable
                style={{ marginBottom: 32 }}
            />
        </>
    )
}
