import './AllDashboardsLink.scss'
import React from 'react'
import { ExportOutlined } from '@ant-design/icons'

export function AllDashboardsLink({ type, apiURL }) {
    return (
        <div className={type === 'float' ? 'toolbar-block' : 'all-dashboards-link'}>
            <a href={`${apiURL}${apiURL.endsWith('/') ? '' : '/'}dashboard`} target="_blank" rel="noopener noreferrer">
                View All Dashboards <ExportOutlined />
            </a>
        </div>
    )
}
