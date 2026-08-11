import { createContext } from 'react'

import type { LemonButtonProps, LemonMenuItem, LemonMenuItems, LemonMenuSection, LemonTagType } from '@posthog/lemon-ui'

export type NotebookComponentToolbarAction = Pick<LemonButtonProps, 'disabledReason' | 'icon'> & {
    text: string
    onClick: () => void
}

export type NotebookComponentToolbarTitleStatus = {
    label: string
    type: LemonTagType
    loading?: boolean
    onClick?: () => void
    tooltip?: string
}

export type NotebookComponentToolbarExtras = {
    actions: NotebookComponentToolbarAction[]
    menuItems: LemonMenuItems | null
    editMenuItems?: LemonMenuItems | null
    title?: string | null
    titleStatus?: NotebookComponentToolbarTitleStatus | null
    /** Disables the shell's filters toggle with this tooltip (e.g. nothing to configure yet). */
    filtersDisabledReason?: string | null
}

function withoutNotebookMenuItemIcons(item: LemonMenuItem): LemonMenuItem {
    if ('items' in item && item.items) {
        return {
            ...item,
            icon: undefined,
            sideIcon: undefined,
            items: item.items.map((nestedItem) => (nestedItem ? withoutNotebookMenuItemIcons(nestedItem) : nestedItem)),
        }
    }

    if (typeof item.label === 'function') {
        return item
    }

    return { ...item, icon: undefined, sideIcon: undefined }
}

export function withoutNotebookMenuIcons(items: LemonMenuItems): LemonMenuItems {
    return items.map((item) => {
        if (!item) {
            return item
        }
        if ('label' in item) {
            return withoutNotebookMenuItemIcons(item)
        }
        return {
            ...(item as LemonMenuSection),
            items: item.items.map((nestedItem) => (nestedItem ? withoutNotebookMenuItemIcons(nestedItem) : nestedItem)),
        }
    })
}

// Bridge for node implementations (mounted inside a panel) to surface their custom
// actions and menu items on the component shell's toolbar, which renders above them.
export const NotebookComponentToolbarExtrasContext = createContext<
    ((extras: NotebookComponentToolbarExtras | null) => void) | null
>(null)
