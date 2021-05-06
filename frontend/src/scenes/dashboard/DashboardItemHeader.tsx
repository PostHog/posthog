import React from 'react'
import { Link } from 'lib/components/Link'
import { PageHeader } from 'lib/components/PageHeader'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { IconDashboard } from 'lib/components/icons'
import { useValues } from 'kea'
import { dashboardLogic } from './dashboardLogic'
import './Dashboard.scss'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'

interface Props {
    dashboardId: number
}

export function DashboardItemHeader({ dashboardId }: Props): JSX.Element {
    const { dashboard } = useValues(dashboardLogic({ id: dashboardId }))
    const { dashboardItem } = useValues(insightLogic)
    const { user } = useValues(userLogic)

    return (
        <div className="dashboard-item-header">
            <Link to={`/dashboard/${dashboardId}`}>
                <ArrowLeftOutlined /> To {dashboard?.name} dashboard
            </Link>
            <div style={{ marginTop: -16 }}>
                <PageHeader title={dashboardItem?.name} />
                <div className="header-container text-default">
                    <div className="title">
                        <IconDashboard />
                        <span style={{ paddingLeft: 6 }}>
                            Viewing graph <b>{dashboardItem?.name}</b> from{' '}
                            <Link to={`/dashboard/${dashboardId}`}>{dashboard?.name}</Link> dashboard.
                        </span>
                    </div>
                    {user?.organization?.available_features?.includes('dashboard_collaboration') && (
                        <>
                            <div className="description">{dashboardItem.description}</div>
                        </>
                    )}
                </div>
            </div>
        </div>
    )
}
