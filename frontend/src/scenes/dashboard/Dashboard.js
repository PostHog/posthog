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

export function Dashboard({ id }) {
    const logic = dashboardLogic({ id: parseInt(id) })
    const { dashboard, itemsLoading, items } = useValues(logic)
    const { user } = useValues(userLogic)
    const { dashboardsLoading } = useValues(dashboardsModel)

    return (
        <div>
            <DashboardHeader logic={logic} />

            {dashboardsLoading ? (
                <SceneLoading />
            ) : !dashboard ? (
                <>
                    <p>Error 404! A dashboard with the ID {id} was not found!</p>
                    <HedgehogOverlay type="sad" />
                </>
            ) : items.length > 0 ? (
                <DashboardItems logic={logic} />
            ) : itemsLoading ? (
                <SceneLoading />
            ) : user.has_events ? (
                <p>
                    You don't have any panels set up. <Link to="/trends">Click here to add some.</Link>
                </p>
            ) : (
                <p />
            )}
        </div>
    )
}
