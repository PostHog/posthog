import './AllActionsLink.scss'
import React from 'react'
import { ExportOutlined } from '@ant-design/icons'

export function AllActionsLink({ type, apiURL }) {
    return (
        <div className={type === 'float' ? 'toolbar-block' : 'all-actions-link'}>
            <a href={`${apiURL}${apiURL.endsWith('/') ? '' : '/'}actions`} target="_blank" rel="noopener noreferrer">
                View & Edit All Actions <ExportOutlined />
            </a>
        </div>
    )
}
