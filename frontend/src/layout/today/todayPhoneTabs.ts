import type { TodayRailPane } from './todayShellLogic'

export const TODAY_PHONE_TAB_LIMIT = 3

export const TODAY_DEFAULT_PHONE_TABS: TodayRailPane[] = ['home', 'analytics', 'products']

export function phoneTabPanes(chosen: TodayRailPane[] | null, railPanes: TodayRailPane[]): TodayRailPane[] {
    const kept = railPanes.filter((pane) => (chosen ?? TODAY_DEFAULT_PHONE_TABS).includes(pane))
    if (kept.length > 0) {
        return kept.slice(0, TODAY_PHONE_TAB_LIMIT)
    }
    return railPanes.filter((pane) => TODAY_DEFAULT_PHONE_TABS.includes(pane))
}

export function togglePhoneTab(
    tabs: TodayRailPane[],
    pane: TodayRailPane,
    railPanes: TodayRailPane[]
): TodayRailPane[] {
    if (tabs.includes(pane)) {
        return tabs.length > 1 ? tabs.filter((tab) => tab !== pane) : tabs
    }
    if (tabs.length >= TODAY_PHONE_TAB_LIMIT) {
        return tabs
    }
    return railPanes.filter((railPane) => railPane === pane || tabs.includes(railPane))
}
