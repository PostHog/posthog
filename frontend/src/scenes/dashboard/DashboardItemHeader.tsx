import React from 'react'
import { Link } from 'lib/components/Link'
import { PageHeader } from 'lib/components/PageHeader'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { IconDashboard } from 'lib/components/icons'
import { useValues } from 'kea'
import { dashboardLogic } from './dashboardLogic'
import { DashboardItemType } from '~/types'
import './Dashboard.scss'

interface Props {
    dashboardItemId: number
    dashboardId: number
}

export function DashboardItemHeader({ dashboardItemId, dashboardId }: Props): JSX.Element {
    const { items, dashboard } = useValues(dashboardLogic({ id: dashboardId }))

    const dashboardItem = items?.find((item: DashboardItemType) => item.id === dashboardItemId)

    return (
        <div className="dashboard-item-header">
            <Link to={`/dashboard/${dashboardId}`}>
                <ArrowLeftOutlined /> Back to {dashboard?.name} dashboard
            </Link>
            <div style={{ marginTop: -16 }}>
                <PageHeader title={dashboardItem?.name} />
                <div className="dashboard-item-description text-default">
                    <div className="title">
                        <IconDashboard />
                        Viewing graph {dashboardItem?.name} from
                        <div style={{ paddingLeft: 4, paddingRight: 4 }}>
                            <Link to={`/dashboard/${dashboardId}`}>{dashboard?.name}</Link>
                        </div>
                        dashboard.
                    </div>
                </div>
            </div>
        </div>
    )
}
