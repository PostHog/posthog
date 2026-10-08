import { ChatsCircleIcon, IconProps, ShapesIcon, SquaresFourIcon } from '@phosphor-icons/react'
import type { ComponentType } from 'react'

import { IconChat } from '@posthog/icons'

import { TodayRailPane } from './todayShellLogic'

export interface TodayRailItem {
    pane: TodayRailPane
    label: string
    Icon: ComponentType<IconProps>
}

// Phosphor has no match for the Spaces mark, so this adapts the PostHog icon to the rail's Phosphor props.
// The size goes inline because the global `.LemonIcon { width: 1em }` rule beats the width attribute.
function SpacesIcon({ size }: IconProps): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <IconChat style={size ? { width: size, height: size } : undefined} />
}

export const TODAY_RAIL_ITEMS: TodayRailItem[] = [
    { pane: 'home', label: 'Work', Icon: ChatsCircleIcon },
    { pane: 'spaces', label: 'Spaces', Icon: SpacesIcon },
    { pane: 'views', label: 'Views', Icon: ShapesIcon },
    { pane: 'products', label: 'Products', Icon: SquaresFourIcon },
]
