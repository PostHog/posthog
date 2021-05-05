import React from 'react'
import { Link } from 'lib/components/Link'
import { PageHeader } from 'lib/components/PageHeader'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { IconDashboard } from 'lib/components/icons'
import { useValues } from 'kea'
import { dashboardLogic } from './dashboardLogic'
import './Dashboard.scss'
import { insightLogic } from 'scenes/insights/insightLogic'

interface Props {
    dashboardId: number
}

export function DashboardItemHeader({ dashboardId }: Props): JSX.Element {
    const { dashboard } = useValues(dashboardLogic({ id: dashboardId }))
    const { dashboardItem } = useValues(insightLogic)

    return (
        <div className="dashboard-item-header">
            <Link to={`/dashboard/${dashboardId}`}>
                <ArrowLeftOutlined /> To {dashboard?.name} dashboard
            </Link>
            <div style={{ marginTop: -16 }}>
                <PageHeader title={dashboardItem?.name} />
                <div className="dashboard-item-description text-default">
                    <div className="title">
                        <IconDashboard />
                        <span style={{ paddingLeft: 6 }}>
                            Viewing graph <b>{dashboardItem?.name}</b> from{' '}
                            <Link to={`/dashboard/${dashboardId}`}>{dashboard?.name}</Link> dashboard.
                        </span>
                    </div>
                </div>
            </div>
        </div>
    )
}
