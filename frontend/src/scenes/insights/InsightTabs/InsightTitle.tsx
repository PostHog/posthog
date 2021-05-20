import React, { useState } from 'react'
import { DashboardOutlined } from '@ant-design/icons'
import { router } from 'kea-router'

export function InsightTitle({ actionBar = null }: { actionBar?: JSX.Element | null }): JSX.Element {
    const [{ fromItemName, fromDashboard }] = useState(router.values.hashParams)
    return (
        <>
            <h3 className="l3" style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap' }}>
                {fromDashboard && (
                    <DashboardOutlined
                        style={{ color: 'var(--warning)', marginRight: 4 }}
                        title="Insight saved on dashboard"
                    />
                )}
                {fromItemName || 'Unsaved query'}
                {actionBar}
            </h3>
        </>
    )
}
