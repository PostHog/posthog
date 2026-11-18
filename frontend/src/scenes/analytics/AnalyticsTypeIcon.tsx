import { IconDashboard, IconGraph, IconNotebook, IconPalette } from '@posthog/icons'

import { AnalyticsType } from './analyticsUtils'

const ICONS: Record<AnalyticsType, JSX.Element> = {
    canvas: <IconPalette />,
    dashboard: <IconDashboard />,
    notebook: <IconNotebook />,
    insight: <IconGraph />,
}

/** The icon that marks an item's type in lists, menus and the sidebar. */
export function AnalyticsTypeIcon({ type }: { type: AnalyticsType }): JSX.Element {
    return ICONS[type]
}
