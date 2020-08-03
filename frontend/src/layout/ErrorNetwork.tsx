import React from 'react'
import { HedgehogOverlay } from 'lib/components/HedgehogOverlay/HedgehogOverlay'
import { Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

export function ErrorNetwork(): JSX.Element {
    return (
        <div>
            <h2>Network Error</h2>
            <p>There was an issue loading the requested resource.</p>
            <p>
                <Button onClick={() => window.location.reload()}>
                    <ReloadOutlined /> Reload the page!
                </Button>
            </p>
            <HedgehogOverlay type="sad" />
        </div>
    )
}
