import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { sharingLogic } from 'lib/components/Sharing/sharingLogic'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import {
    AccessControlLevel,
    AccessControlResourceType,
    DashboardPlacement,
    DashboardType,
    QueryBasedInsightModel,
} from '~/types'

import {
    DashboardAutoRefreshRestriction,
    dashboardAutoRefreshRestrictionText,
    getDashboardAutoRefreshRestriction,
    getLast7DaysDashboardFilters,
} from './dashboardAutoRefresh'
import { dashboardLogic } from './dashboardLogic'

const AUTHENTICATED_DASHBOARD_PLACEMENTS = [
    DashboardPlacement.Dashboard,
    DashboardPlacement.ProjectHomepage,
    DashboardPlacement.Builtin,
]

export function DashboardAutoRefreshRestrictionNotice({
    dashboard,
    restriction,
    canEdit,
}: {
    dashboard: DashboardType<QueryBasedInsightModel>
    restriction: DashboardAutoRefreshRestriction
    canEdit: boolean
}): JSX.Element {
    const { triggerDashboardUpdate } = useActions(
        dashboardLogic({ id: dashboard.id, dashboard, placement: DashboardPlacement.Dashboard })
    )
    const { dashboardLoading } = useValues(dashboardsModel)
    const [dismissed, setDismissed] = useState(false)

    if (dismissed) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            onClose={() => setDismissed(true)}
            action={
                canEdit
                    ? {
                          children: 'Set to last 7 days',
                          loading: dashboardLoading,
                          onClick: () => triggerDashboardUpdate({ filters: getLast7DaysDashboardFilters(dashboard) }),
                      }
                    : undefined
            }
        >
            {dashboardAutoRefreshRestrictionText(restriction)}
        </LemonBanner>
    )
}

export function DashboardAutoRefreshRestrictionBanner({
    placement,
}: {
    placement: DashboardPlacement
}): JSX.Element | null {
    if (!AUTHENTICATED_DASHBOARD_PLACEMENTS.includes(placement)) {
        return null
    }

    return <DashboardAutoRefreshRestrictionBannerContent />
}

function DashboardAutoRefreshRestrictionBannerContent(): JSX.Element | null {
    const { dashboard } = useValues(dashboardLogic)
    const { currentTeam } = useValues(teamLogic)
    const { sharingConfiguration } = useValues(sharingLogic({ dashboardId: dashboard?.id }))
    const restriction = getDashboardAutoRefreshRestriction(dashboard, currentTeam?.timezone ?? 'UTC')

    if (!dashboard || !restriction || !sharingConfiguration?.enabled) {
        return null
    }

    const canEdit = dashboard.user_access_level
        ? accessLevelSatisfied(
              AccessControlResourceType.Dashboard,
              dashboard.user_access_level,
              AccessControlLevel.Editor
          )
        : true

    return <DashboardAutoRefreshRestrictionNotice dashboard={dashboard} restriction={restriction} canEdit={canEdit} />
}
