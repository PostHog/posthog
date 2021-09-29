import React from 'react'
import { Alert } from 'antd'

export function CloudAnnouncement({ message }: { message: string }): JSX.Element | null {
    return (
        <div style={{ marginTop: 15 }}>
            <Alert message={message.split('_').join(' ')} type="warning" showIcon closable />
        </div>
    )
}
