import React from 'react'
import { Button } from 'antd'
import { useActions } from 'kea'
import { MenuUnfoldOutlined } from '@ant-design/icons'
export function FloatingToolbarHeader({ dockLogic }) {
    const { dock } = useActions(dockLogic)
    return (
        <div className="toolbar-block no-padding posthog-header-block">
            <div>PostHog</div>
            <div>
                <Button onClick={dock}>
                    Dock <MenuUnfoldOutlined />
                </Button>
            </div>
        </div>
    )
}
