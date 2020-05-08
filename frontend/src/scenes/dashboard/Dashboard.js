import React from 'react'
import { Link } from 'lib/components/Link'
import { SceneLoading } from 'lib/utils'
import { useValues } from 'kea'
import { userLogic } from 'scenes/userLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardHeader } from 'scenes/dashboard/DashboardHeader'
import { DashboardItems } from 'scenes/dashboard/DashboardItems'

export function Dashboard({ id }) {
    const logic = dashboardLogic({ id: parseInt(id) })
    const { dashboardItemsLoading, items } = useValues(logic)
    const { user } = useValues(userLogic)

    return (
        <div>
            <DashboardHeader logic={logic} />

            {items.length > 0 ? (
                <DashboardItems logic={logic} />
            ) : dashboardItemsLoading ? (
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
