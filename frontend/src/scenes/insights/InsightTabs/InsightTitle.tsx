import React from 'react'
import { DashboardOutlined } from '@ant-design/icons'
import { router } from 'kea-router'
import { useValues } from 'kea'

export function InsightTitle({ actionBar = null }: { actionBar?: JSX.Element | null }): JSX.Element {
    const {
        hashParams: { fromItemName, fromDashboard },
    } = useValues(router)
    return (
        <>
            <h3 className="l3 insight-title-container">
                {fromDashboard && (
                    <DashboardOutlined
                        style={{ color: 'var(--warning)', marginRight: 4 }}
                        title="Insight saved on dashboard"
                    />
                )}
                <div className="insight-title-text">{fromItemName || 'Unsaved query'}</div>
                {actionBar}
            </h3>
        </>
    )
}
