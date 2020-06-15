import './AllActionsLink.scss'
import React from 'react'
import { ExportOutlined } from '@ant-design/icons'
import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export function AllActionsLink({ type }) {
    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className={type === 'float' ? 'toolbar-block' : 'all-actions-link'}>
            <a href={`${apiURL}${apiURL.endsWith('/') ? '' : '/'}actions`} target="_blank" rel="noopener noreferrer">
                View & Edit All Actions <ExportOutlined />
            </a>
        </div>
    )
}
