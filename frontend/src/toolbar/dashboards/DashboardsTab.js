import React from 'react'

import { AllDashboardsLink } from '~/toolbar/dashboards/AllDashboardsLink'

export function DashboardsTab({ className, type }) {
    return (
        <div className={`toolbar-content ${className}`}>
            <AllDashboardsLink type={type} />
        </div>
    )
}
