import React from 'react'
import { useActions } from 'kea'
import { Button, Popconfirm } from 'antd'
import { ApiOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'

export function OptOutPlugins(): JSX.Element {
    const { userUpdateRequest } = useActions(userLogic)

    return (
        <div style={{ float: 'right' }}>
            <Popconfirm
                title="Are you sure you want to disable plugins?"
                onConfirm={() => userUpdateRequest({ team: { plugins_opt_in: false } })}
                onCancel={() => null}
                okText="Yes"
                cancelText="No"
            >
                <Button>
                    <ApiOutlined /> Disable plugins for this project
                </Button>
            </Popconfirm>
        </div>
    )
}
