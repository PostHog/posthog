import React from 'react'
import { kea, useActions, useValues } from 'kea'
import { Alert, Button } from 'antd'
import { StarOutlined, SettingOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'

const asyncWarningLogic = kea({
    actions: {
        dismissWarning: true,
    },
    reducers: {
        warningDismissed: [
            false,
            { persist: true },
            {
                dismissWarning: () => true,
            },
        ],
    },
})

export function AsyncActionWarning(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { warningDismissed } = useValues(asyncWarningLogic)
    const { dismissWarning } = useActions(asyncWarningLogic)

    if (warningDismissed || !user?.is_async_event_action_mapping_enabled) {
        return null
    }
    return (
        <>
            <Alert
                type={'warning'}
                message={'Slow actions warning'}
                className="demo-warning"
                description={<>Async events might be delayed by up to 5 minutes</>}
                icon={<StarOutlined />}
                showIcon
                action={
                    <Button onClick={dismissWarning} data-attr="async-warning-cta">
                        <SettingOutlined /> Dismiss
                    </Button>
                }
                closable
                style={{ marginTop: 32 }}
                onClose={dismissWarning}
            />
        </>
    )
}
