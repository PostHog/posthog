import React from 'react'
import { Button } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'

export function ErrorNetwork(): JSX.Element {
    return (
        <div>
            <h1 className="page-title">Network Error</h1>
            <p>There was an issue loading the requested resource.</p>
            <p>
                <Button onClick={() => window.location.reload()}>
                    <ReloadOutlined /> Reload the page!
                </Button>
            </p>
        </div>
    )
}
