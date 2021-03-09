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
import { CalendarOutlined } from '@ant-design/icons'

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
    const { dashboard, itemsLoading, items, isOnSharedMode } = useValues(dashboardLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)
    const { updateAndRefreshDashboard } = useActions(dashboardLogic)

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
        <div style={{ marginTop: 32 }}>
            {!isOnSharedMode && <DashboardHeader />}

            {items && items.length ? (
                <div>
                    <div className="text-right mb">
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
