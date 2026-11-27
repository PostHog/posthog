import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

/**
 * `isTodayHomePaneEnabled` for a component. Both hooks always run, so the hook order stays fixed. It lives apart from
 * `todayPaneFlags`, which the eager shell logic imports, so the hook stays off the eager path.
 */
export function useTodayHomePaneEnabled(): boolean {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const todayHomePane = useFeatureFlag('TODAY_HOME_PANE')
    return todayRailNav && todayHomePane
}
