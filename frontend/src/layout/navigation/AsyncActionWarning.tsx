import React from 'react'
import { kea, useActions, useValues } from 'kea'
import { Alert } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'

const asyncWarningLogic = kea({
    actions: {
        dismissWarning: true,
    },
    reducers: {
        warningDismissed: [
            false,
            { persist: true }, // dismiss forever if dismissed
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
                message={'Webhooks and actions delayed up to 5 minutes'}
                className="demo-warning"
                description={
                    <>Due to temporary limitations, webhooks and actions might be delayed by up to 5 minutes.</>
                }
                icon={<InfoCircleOutlined />}
                showIcon
                closable
                style={{ marginTop: 32 }}
                onClose={dismissWarning}
            />
        </>
    )
}
