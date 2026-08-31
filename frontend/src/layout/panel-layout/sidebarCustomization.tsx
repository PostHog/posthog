import {
    IconApps,
    IconClock,
    IconDatabase,
    IconFolder,
    IconFolderOpen,
    IconGear,
    IconHome,
    IconNotification,
    IconQuestion,
    IconStar,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'

import { SidebarItemKey, SidebarSectionKey } from '~/layout/uiCustomizationLogic'

export interface SidebarCustomizableItem {
    /** Absent for items that always stay visible (they render a locked switch). */
    key?: SidebarItemKey
    label: string
    /** Very brief explanation of what the item opens, shown under the label in settings. */
    description: string
    icon: JSX.Element
    /** Mirrors the flag gating the item in the navbar, so the toggle is only offered when the item can render at all. */
    flag?: string
}

export interface SidebarCustomizableSection {
    key: SidebarSectionKey
    label: string
    description: string
    icon: JSX.Element
    items: SidebarCustomizableItem[]
}

/**
 * The exhaustive list of customizable sidebar elements, used to render the settings UI.
 * Keys must match the UserUIConfiguration schema and labels/icons must match what the
 * navbar renders (NavTabBrowse and NavBarFooter), so keep the three in sync.
 * Activity and Settings have no key: they always stay visible.
 */
export const SIDEBAR_CUSTOMIZABLE_SECTIONS: SidebarCustomizableSection[] = [
    {
        key: 'project',
        label: 'Project',
        description: 'The core navigation for your project.',
        icon: <IconFolder />,
        items: [
            { key: 'home', label: 'Home', description: 'Opens your homepage.', icon: <IconHome /> },
            {
                key: 'inbox',
                label: 'Self-driving',
                description: 'Reports and signals that need your attention.',
                icon: <IconNotification />,
                flag: FEATURE_FLAGS.PRODUCT_AUTONOMY,
            },
            {
                label: 'Activity',
                description: 'A live stream of events coming into your project.',
                icon: <IconClock />,
            },
            {
                key: 'data',
                label: 'Data',
                description: 'Manage events, actions, properties, and people.',
                icon: <IconDatabase />,
            },
            {
                key: 'files',
                label: 'Files',
                description: 'Everything saved in your project, organized in folders.',
                icon: <IconFolderOpen />,
            },
            { key: 'tools', label: 'Tools', description: 'Browse all PostHog tools.', icon: <IconApps /> },
            {
                key: 'starred',
                label: 'Starred',
                description: 'Quick access to items you starred.',
                icon: <IconStar />,
            },
        ],
    },
    {
        key: 'recents',
        label: 'Recents',
        description: 'Items you viewed recently.',
        icon: <IconClock />,
        items: [],
    },
    {
        key: 'my_tools',
        label: 'My Tools',
        description: 'The tools you picked for quick access.',
        icon: <IconApps />,
        items: [],
    },
]

/** Customizable items at the bottom of the sidebar. */
export const SIDEBAR_CUSTOMIZABLE_FOOTER_ITEMS: SidebarCustomizableItem[] = [
    {
        key: 'notifications',
        label: 'Notifications',
        description: 'Your in-app notifications.',
        icon: <IconNotification />,
        flag: FEATURE_FLAGS.REAL_TIME_NOTIFICATIONS,
    },
    { key: 'help', label: 'Help', description: 'Docs, support, and product updates.', icon: <IconQuestion /> },
    {
        label: 'Settings',
        description: 'Project, organization, and account settings.',
        icon: <IconGear />,
    },
]
