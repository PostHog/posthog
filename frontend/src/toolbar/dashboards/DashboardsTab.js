import React from 'react'

import { AllDashboardsLink } from '~/toolbar/dashboards/AllDashboardsLink'

export function DashboardsTab({ apiURL, className, type }) {
    return (
        <div className={`toolbar-content ${className}`}>
            <AllDashboardsLink apiURL={apiURL} type={type} />
        </div>
    )
}
