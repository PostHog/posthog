import { IconBook, IconChat, IconEllipsis, IconHome, IconTrends, IconWrench } from '@posthog/icons'

import { TODAY_MORE_PANES, TodayRailPane } from './todayShellLogic'

export interface TodayRailItem {
    pane: TodayRailPane
    label: string
    icon: JSX.Element
}

export const TODAY_RAIL_ITEMS: TodayRailItem[] = [
    { pane: 'home', label: 'Home', icon: <IconHome /> },
    { pane: 'spaces', label: 'Spaces', icon: <IconChat /> },
    { pane: 'analytics', label: 'Analytics', icon: <IconTrends /> },
    { pane: 'library', label: 'Library', icon: <IconBook /> },
    { pane: 'tools', label: 'Tools', icon: <IconWrench /> },
]

export const TODAY_TAB_BAR_ITEMS: TodayRailItem[] = [
    ...TODAY_RAIL_ITEMS.filter(({ pane }) => !TODAY_MORE_PANES.includes(pane)),
    { pane: 'more', label: 'More', icon: <IconEllipsis /> },
]

export const TODAY_MORE_ITEMS: (TodayRailItem & { description: string })[] = [
    { pane: 'library', label: 'Library', icon: <IconBook />, description: 'Flags, experiments, cohorts and more' },
    { pane: 'tools', label: 'Tools', icon: <IconWrench />, description: 'The SQL editor and product tools' },
]
