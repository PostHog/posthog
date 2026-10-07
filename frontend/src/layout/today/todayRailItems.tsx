import {
    BookOpenTextIcon,
    ChatsCircleIcon,
    DotsThreeIcon,
    IconProps,
    ShapesIcon,
    WrenchIcon,
} from '@phosphor-icons/react'
import type { ComponentType } from 'react'

import { TODAY_MORE_PANES, TodayRailPane } from './todayShellLogic'
import { TodaySpacesIcon } from './TodaySpacesIcon'

export interface TodayRailItem {
    pane: TodayRailPane
    label: string
    Icon: ComponentType<IconProps>
}

export const TODAY_RAIL_ITEMS: TodayRailItem[] = [
    { pane: 'home', label: 'Work', Icon: ChatsCircleIcon },
    { pane: 'spaces', label: 'Spaces', Icon: TodaySpacesIcon },
    { pane: 'views', label: 'Views', Icon: ShapesIcon },
    { pane: 'library', label: 'Library', Icon: BookOpenTextIcon },
    { pane: 'tools', label: 'Tools', Icon: WrenchIcon },
]

export const TODAY_TAB_BAR_ITEMS: TodayRailItem[] = [
    ...TODAY_RAIL_ITEMS.filter(({ pane }) => !TODAY_MORE_PANES.includes(pane)),
    { pane: 'more', label: 'More', Icon: DotsThreeIcon },
]

export const TODAY_MORE_ITEMS: (TodayRailItem & { description: string })[] = [
    {
        pane: 'library',
        label: 'Library',
        Icon: BookOpenTextIcon,
        description: 'Saved insights, flags, cohorts and more',
    },
    { pane: 'tools', label: 'Tools', Icon: WrenchIcon, description: 'The SQL editor and product tools' },
]
