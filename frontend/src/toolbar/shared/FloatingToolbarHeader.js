import React from 'react'
import { Button } from 'antd'
import { useActions } from 'kea'
import { MenuUnfoldOutlined, MinusSquareOutlined } from '@ant-design/icons'
export function FloatingToolbarHeader({ dockLogic }) {
    const { dock, button } = useActions(dockLogic)
    return (
        <div className="toolbar-block no-padding posthog-header-block">
            <div>PostHog</div>
            <div>
                <Button onClick={button}>
                    Button <MinusSquareOutlined />
                </Button>
                <Button onClick={dock}>
                    Dock <MenuUnfoldOutlined />
                </Button>
            </div>
        </div>
    )
}
