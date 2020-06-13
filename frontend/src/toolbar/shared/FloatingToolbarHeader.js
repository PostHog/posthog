import React from 'react'
import { Button } from 'antd'
import { useActions } from 'kea'
import { CloseOutlined } from '@ant-design/icons'
import { dockLogic } from '~/toolbar/dockLogic'

export function FloatingToolbarHeader() {
    const { button } = useActions(dockLogic)
    return (
        <div className="toolbar-block no-padding posthog-header-block">
            <div className="floating-title">PostHog</div>
            <div className="floating-buttons">
                <Button onClick={button}>
                    Close <CloseOutlined />
                </Button>
            </div>
        </div>
    )
}
