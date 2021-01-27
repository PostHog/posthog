import React from 'react'
import { useValues } from 'kea'
import { Alert } from 'antd'
import { StarOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'

export function DemoWarning(): JSX.Element | null {
    const { user, demoOnlyUser } = useValues(userLogic)

    if (!demoOnlyUser) {
        return null
    }

    return (
        <>
            <Alert
                type="warning"
                message={`Get started using Posthog, ${user?.name}`}
                description={
                    <span>You're currently viewing demo data. Go to setup to start sending your own data!</span>
                }
                icon={<StarOutlined />}
                showIcon
            />
        </>
    )
}
