import { createContext } from 'react'

import type { LemonButtonProps, LemonMenuItems } from '@posthog/lemon-ui'

export type NotebookComponentToolbarAction = Pick<LemonButtonProps, 'icon'> & {
    text: string
    onClick: () => void
}

export type NotebookComponentToolbarExtras = {
    actions: NotebookComponentToolbarAction[]
    menuItems: LemonMenuItems | null
    /** Disables the shell's filters toggle with this tooltip (e.g. nothing to configure yet). */
    filtersDisabledReason?: string | null
}

// Bridge for node implementations (mounted inside a panel) to surface their custom
// actions and menu items on the component shell's toolbar, which renders above them.
export const NotebookComponentToolbarExtrasContext = createContext<
    ((extras: NotebookComponentToolbarExtras | null) => void) | null
>(null)
