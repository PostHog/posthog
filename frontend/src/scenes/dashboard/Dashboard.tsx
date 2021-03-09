import React from 'react'
import { Link } from 'lib/components/Link'
import { SceneLoading } from 'lib/utils'
import { BindLogic, useActions, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardsModel } from '~/models/dashboardsModel'
import { hot } from 'react-hot-loader/root'
import { DateFilter } from 'lib/components/DateFilter'
import { CalendarOutlined, ReloadOutlined } from '@ant-design/icons'
import moment from 'moment'
import { Button } from 'antd'
import './Dashboard.scss'

interface Props {
    id: string
    shareToken?: string
}

export const Dashboard = hot(_Dashboard)
function _Dashboard({ id, shareToken }: Props): JSX.Element {
    return (
        <BindLogic logic={dashboardLogic} props={{ id: parseInt(id), shareToken }}>
            <DashboardView />
        </BindLogic>
    )
}

function DashboardView(): JSX.Element {
    const { dashboard, itemsLoading, items, isOnSharedMode, lastRefreshed } = useValues(dashboardLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { updateAndRefreshDashboard, refreshAllDashboardItems } = useActions(dashboardLogic)

    if (dashboardsLoading || itemsLoading) {
        return <SceneLoading />
    }

    if (!dashboard) {
        return (
            <>
                <p>Dashboard not found.</p>
            </>
        )
    }

    return (
        <div className="dashboard">
            {!isOnSharedMode && <DashboardHeader />}

            {items && items.length ? (
                <div>
                    <div className="dashboard-items-actions">
                        <div className="left-item">
                            Last updated <b>{moment(lastRefreshed).fromNow() || 'a while ago'}</b>
                            <Button type="link" icon={<ReloadOutlined />} onClick={refreshAllDashboardItems}>
                                Refresh
                            </Button>
                        </div>
                        <DateFilter
                            defaultValue="Custom"
                            showCustom
                            onChange={updateAndRefreshDashboard}
                            makeLabel={(key) => (
                                <>
                                    <CalendarOutlined />
                                    <span className="hide-when-small"> {key}</span>
                                </>
                            )}
                        />
                    </div>
                    <DashboardItems inSharedMode={isOnSharedMode} />
                </div>
            ) : (
                <p>
                    There are no panels on this dashboard.{' '}
                    <Link to="/insights?insight=TRENDS">Click here to add some!</Link>
                </p>
            )}
        </div>
    )
}
