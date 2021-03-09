import React from 'react'
import { Link } from 'lib/components/Link'
import { SceneLoading } from 'lib/utils'
import { BindLogic, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardsModel } from '~/models/dashboardsModel'
import { hot } from 'react-hot-loader/root'

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
                <DashboardItems inSharedMode={isOnSharedMode} />
            ) : (
                <p>
                    There are no panels on this dashboard.{' '}
                    <Link to="/insights?insight=TRENDS">Click here to add some!</Link>
                </p>
            )}
        </div>
    )
}
