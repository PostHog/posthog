import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

export function DashboardsV2Gate({ children }: { children: JSX.Element }): JSX.Element {
    const dashboardsV2 = useFeatureFlag('DASHBOARDS_V2_PRODUCT')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!dashboardsV2 || !todayRailNav) {
        return <NotFound object="page" />
    }
    return children
}
