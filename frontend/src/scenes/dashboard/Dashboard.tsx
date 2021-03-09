import React from 'react'
import { Link } from 'lib/components/Link'
import { SceneLoading } from 'lib/utils'
import { BindLogic, useValues } from 'kea'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardsModel } from '~/models/dashboardsModel'
import { HedgehogOverlay } from 'lib/components/HedgehogOverlay/HedgehogOverlay'
import { hot } from 'react-hot-loader/root'

interface Props {
    id: string
    shareToken?: string
}

export const Dashboard = hot(_Dashboard)
function _Dashboard({ id, shareToken }: Props): JSX.Element {
    return (
        <BindLogic logic={dashboardLogic} props={{ id: parseInt(id), shareToken }}>
            <DashboardView id={id} shareToken={shareToken} />
        </BindLogic>
    )
}

function DashboardView({ id, shareToken }: Props): JSX.Element {
    const { dashboard, itemsLoading, items } = useValues(dashboardLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    if (dashboardsLoading || itemsLoading) {
        return <SceneLoading />
    }

    if (!dashboard) {
        return (
            <>
                <p>A dashboard with the ID {id} was not found!</p>
                <HedgehogOverlay type="sad" />
            </>
        )
    }

    return (
        <div style={{ marginTop: 32 }}>
            {!shareToken && <DashboardHeader />}

            {items && items.length ? (
                <DashboardItems inSharedMode={!!shareToken} />
            ) : (
                <p>
                    There are no panels on this dashboard.{' '}
                    <Link to="/insights?insight=TRENDS">Click here to add some!</Link>
                </p>
            )}
        </div>
    )
}
