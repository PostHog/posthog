import { ChatsCircleIcon, IconProps, ShapesIcon, SquaresFourIcon } from '@phosphor-icons/react'
import type { ComponentType } from 'react'

import { TodayRailPane } from './todayShellLogic'
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
    { pane: 'products', label: 'Products', Icon: SquaresFourIcon },
]
