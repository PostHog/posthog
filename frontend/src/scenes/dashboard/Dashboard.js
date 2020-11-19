import React from 'react'
import { Link } from 'lib/components/Link'
import { SceneLoading } from 'lib/utils'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'
import { dashboardsModel } from '~/models/dashboardsModel'
import { HedgehogOverlay } from 'lib/components/HedgehogOverlay/HedgehogOverlay'
import { hot } from 'react-hot-loader/root'

export const Dashboard = hot(_Dashboard)
function _Dashboard({ id, shareToken }) {
    const logic = dashboardLogic({ id: parseInt(id), shareToken })
    const { dashboard, itemsLoading, items } = useValues(logic)
    const { user } = useValues(userLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    return (
        <div style={{ marginTop: 32 }}>
            {!shareToken && <DashboardHeader id={id} logic={logic} />}

            {dashboardsLoading ? (
                <SceneLoading />
            ) : !dashboard ? (
                <>
                    <p>A dashboard with the ID {id} was not found!</p>
                    <HedgehogOverlay type="sad" />
                </>
            ) : items && items.length > 0 ? (
                <DashboardItems logic={logic} inSharedMode={!!shareToken} />
            ) : itemsLoading ? (
                <SceneLoading />
            ) : user?.team?.ingested_event ? (
                <p>
                    There are no panels on this dashboard.{' '}
                    <Link to="/insights?insight=TRENDS">Click here to add some!</Link>
                </p>
            ) : (
                <p />
            )}
        </div>
    )
}
