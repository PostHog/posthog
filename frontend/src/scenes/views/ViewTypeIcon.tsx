import { IconDashboard, IconNotebook, IconPalette } from '@posthog/icons'

import { ViewType } from './viewsUtils'

/** The icon that marks a view's type in lists, menus and the sidebar. */
export function ViewTypeIcon({ type }: { type: ViewType }): JSX.Element {
    return type === 'canvas' ? <IconPalette /> : type === 'notebook' ? <IconNotebook /> : <IconDashboard />
}
