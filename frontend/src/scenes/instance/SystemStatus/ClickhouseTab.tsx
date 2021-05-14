import React from 'react'
import { Card } from 'antd'
import { useValues } from 'kea'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { systemStatusLogic } from 'scenes/instance/SystemStatus/systemStatusLogic'

export function ClickhouseTab(): JSX.Element {
    const { systemStatus } = useValues(systemStatusLogic)

    const dashboard = systemStatus?.internal_metrics.clickhouse

    return (
        <Card>{dashboard ? <Dashboard id={dashboard.id.toString()} shareToken={dashboard.share_token} /> : null}</Card>
    )
}
