import React from 'react'
import { useActions } from 'kea'
import { Button, Card, Popconfirm } from 'antd'
import { ApiOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import posthog from 'posthog-js'
import Paragraph from 'antd/es/typography/Paragraph'
import Title from 'antd/es/typography/Title'

export function DangerZone(): JSX.Element {
    const { userUpdateRequest } = useActions(userLogic)

    return (
        <div style={{ marginTop: 16 }}>
            <Title level={3} type="danger">
                Danger Zone
            </Title>
            <Card style={{ borderColor: 'red' }}>
                <Title level={5} type="danger">
                    Opt Out of Plugins
                </Title>
                <Paragraph type="danger">
                    The plugin server will be a necessary part of PostHog in a future release. Until then, you can
                    disable the plugin server here.
                </Paragraph>
                <Popconfirm
                    title="Are you sure you want to disable plugins?"
                    onConfirm={() => {
                        userUpdateRequest({ team: { plugins_opt_in: false } })
                        posthog.capture('plugins disabled for project')
                    }}
                    onCancel={() => null}
                    okText="Yes"
                    cancelText="No"
                >
                    <Button danger type="default" icon={<ApiOutlined />}>
                        Disable plugins for this project
                    </Button>
                </Popconfirm>
            </Card>
        </div>
    )
}
