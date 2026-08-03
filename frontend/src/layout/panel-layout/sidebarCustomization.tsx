import {
    IconApps,
    IconClock,
    IconDatabase,
    IconFolder,
    IconFolderOpen,
    IconGear,
    IconHome,
    IconNotification,
    IconPin,
    IconQuestion,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'

import { SidebarItemKey, SidebarSectionKey } from '~/layout/uiCustomizationLogic'
import { SidebarConfiguration } from '~/queries/schema/schema-general'

export interface SidebarCustomizableItem {
    /** Absent for items that always stay visible (they render a locked switch). */
    key?: SidebarItemKey
    /** Identity used for ordering. Present on every orderable item, including always-visible ones. */
    orderKey?: string
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
            { key: 'home', orderKey: 'home', label: 'Home', description: 'Opens your homepage.', icon: <IconHome /> },
            {
                key: 'inbox',
                orderKey: 'inbox',
                label: 'Inbox',
                description: 'Reports and signals that need your attention.',
                icon: <IconNotification />,
                flag: FEATURE_FLAGS.PRODUCT_AUTONOMY,
            },
            {
                orderKey: 'activity',
                label: 'Activity',
                description: 'A live stream of events coming into your project.',
                icon: <IconClock />,
            },
            {
                key: 'data',
                orderKey: 'data',
                label: 'Data',
                description: 'Manage events, actions, properties, and people.',
                icon: <IconDatabase />,
            },
            {
                key: 'files',
                orderKey: 'files',
                label: 'Files',
                description: 'Everything saved in your project, organized in folders.',
                icon: <IconFolderOpen />,
            },
            {
                key: 'tools',
                orderKey: 'tools',
                label: 'Tools',
                description: 'Browse all PostHog tools.',
                icon: <IconApps />,
            },
            {
                key: 'starred',
                label: 'Pinned',
                description: 'Quick access to items you pinned to your sidebar.',
                icon: <IconPin />,
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

/** Default display order of the main sidebar items, by orderKey. */
export const DEFAULT_SIDEBAR_ITEM_ORDER: string[] = SIDEBAR_CUSTOMIZABLE_SECTIONS[0].items
    .map((item) => item.orderKey)
    .filter((orderKey): orderKey is string => !!orderKey)

export interface SidebarPreset {
    key: string
    label: string
    description: string
    /** The sidebar configuration this preset applies. Null restores PostHog defaults. */
    sidebar: SidebarConfiguration | null
}

/**
 * Canned sidebar layouts, applied wholesale from settings. A preset replaces the sidebar
 * part of the configuration; per-project overrides like accent colors are kept.
 */
export const SIDEBAR_PRESETS: SidebarPreset[] = [
    {
        key: 'default',
        label: 'PostHog default',
        description: 'Everything in its default place.',
        sidebar: null,
    },
    {
        key: 'analytics',
        label: 'Analytics',
        description: 'Data first. Hides the inbox and recents.',
        sidebar: {
            items: {
                inbox: { visible: false },
            },
            sections: {
                recents: { visible: false },
            },
            itemOrder: ['home', 'data', 'activity', 'tools', 'files'],
        },
    },
    {
        key: 'minimal',
        label: 'Minimal',
        description: 'A compact, flat list with only the essentials.',
        sidebar: {
            flattened: true,
            density: 'compact',
            items: {
                inbox: { visible: false },
                data: { visible: false },
                files: { visible: false },
                starred: { visible: false },
                notifications: { visible: false },
                help: { visible: false },
            },
            sections: {
                recents: { visible: false },
                my_tools: { visible: false },
            },
        },
    },
]
