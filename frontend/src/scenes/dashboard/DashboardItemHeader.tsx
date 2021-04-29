import React from 'react'
import { Link } from 'lib/components/Link'
import { PageHeader } from 'lib/components/PageHeader'
import { ArrowLeftOutlined } from '@ant-design/icons'
import './Dashboard.scss'
import { IconDashboard } from 'lib/components/icons'
import { useValues } from 'kea'
import { dashboardLogic } from './dashboardLogic'

export function DashboardItemHeader(): JSX.Element {
    const dashboardItem = { name: 'App WAUs', dashboardName: 'Feature Usage', id: 5 }
    const { items } = useValues(dashboardLogic({ id: 5 }))
    console.log(items)
    return (
        <div className="dashboard-item-header">
            <Link to={`/dashboard/${dashboardItem.id}`}>
                <ArrowLeftOutlined /> Back to {dashboardItem.dashboardName} dashboard
            </Link>
            <div style={{ marginTop: -16 }}>
                <PageHeader title={dashboardItem.name} />
                <div className="dashboard-item-description text-default">
                    <div className="title">
                        <IconDashboard />
                        Viewing graph {dashboardItem.name} from
                        <div style={{ paddingLeft: 4, paddingRight: 4 }}>
                            <Link to={`/dashboard/${dashboardItem.id}`}>{dashboardItem.dashboardName}</Link>
                        </div>
                        dashboard.
                    </div>
                </div>
            </div>
        </div>
    )
}
