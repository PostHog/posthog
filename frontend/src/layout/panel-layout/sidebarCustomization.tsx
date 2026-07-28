import {
    IconApps,
    IconClock,
    IconDatabase,
    IconFolder,
    IconFolderOpen,
    IconHome,
    IconNotification,
    IconQuestion,
    IconStar,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'

import { SidebarItemKey, SidebarSectionKey } from '~/layout/uiCustomizationLogic'

export interface SidebarCustomizableItem {
    key: SidebarItemKey
    label: string
    icon: JSX.Element
    /** Mirrors the flag gating the item in the navbar, so the toggle is only offered when the item can render at all. */
    flag?: string
}

export interface SidebarCustomizableSection {
    key: SidebarSectionKey
    label: string
    icon: JSX.Element
    items: SidebarCustomizableItem[]
}

/**
 * The exhaustive list of customizable sidebar elements, used to render the settings UI.
 * Keys must match the UserUIConfiguration schema and labels/icons must match what the
 * navbar renders (NavTabBrowse and NavBarFooter), so keep the three in sync.
 */
export const SIDEBAR_CUSTOMIZABLE_SECTIONS: SidebarCustomizableSection[] = [
    {
        key: 'project',
        label: 'Project',
        icon: <IconFolder />,
        items: [
            { key: 'home', label: 'Home', icon: <IconHome /> },
            { key: 'inbox', label: 'Inbox', icon: <IconNotification />, flag: FEATURE_FLAGS.PRODUCT_AUTONOMY },
            { key: 'activity', label: 'Activity', icon: <IconClock /> },
            { key: 'data', label: 'Data', icon: <IconDatabase /> },
            { key: 'files', label: 'Files', icon: <IconFolderOpen /> },
            { key: 'tools', label: 'Tools', icon: <IconApps /> },
            { key: 'starred', label: 'Starred', icon: <IconStar /> },
        ],
    },
    { key: 'recents', label: 'Recents', icon: <IconClock />, items: [] },
    { key: 'my_tools', label: 'My Tools', icon: <IconApps />, items: [] },
]

/** Customizable items at the bottom of the sidebar. Settings is deliberately absent: it always shows. */
export const SIDEBAR_CUSTOMIZABLE_FOOTER_ITEMS: SidebarCustomizableItem[] = [
    {
        key: 'notifications',
        label: 'Notifications',
        icon: <IconNotification />,
        flag: FEATURE_FLAGS.REAL_TIME_NOTIFICATIONS,
    },
    { key: 'help', label: 'Help', icon: <IconQuestion /> },
]
