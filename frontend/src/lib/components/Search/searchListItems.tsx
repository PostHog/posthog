import { router } from 'kea-router'

import { IconClock, IconDownload, IconLeave, IconNotification, IconSupport, IconTerminal } from '@posthog/icons'

import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { isFileSystemImportFlagEnabled } from 'lib/utils/fileSystemImportFlags'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { PLACEHOLDER_HREF } from 'lib/utils/navigateToHref'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { toSentenceCase } from 'lib/utils/strings'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { isDefinitionsTabHref } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { getDefaultTreePersons } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { getTreeItemsMetadata, getTreeItemsNew, getTreeItemsProducts } from '~/products'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'
import type { SettingId, SettingLevelId, SettingSection, SettingSectionId } from '~/scenes/settings/types'
import { ActivityTab } from '~/types'

import { SearchItem, fileSystemEntryToSearchItem } from './searchItems'
import { SEARCH_TAB_CATEGORY } from './utils'

/** Max starred shortcuts shown in quick search (folders excluded). */
export const STARRED_LIMIT = 20

type SceneViews = Record<string, string>

interface FixedSearchItem extends SearchItem {
    sceneKey?: string
}

const CATEGORY_SEARCH_KEYWORDS: Record<string, string[]> = {
    CDP: ['data pipelines', 'data pipeline', 'pipeline', 'cdp'],
}

const fixedItem = (
    id: string,
    name: string,
    category: string,
    fields: Partial<FixedSearchItem> = {}
): FixedSearchItem => ({ id, name, displayName: name, category, ...fields })

const lastViewedAt = (sceneKey: string | undefined, sceneViews: SceneViews): string | null =>
    sceneKey ? (sceneViews[sceneKey] ?? null) : null

const withLastViewed = ({ sceneKey, ...item }: FixedSearchItem, sceneViews: SceneViews): SearchItem =>
    sceneKey ? { ...item, lastViewedAt: lastViewedAt(sceneKey, sceneViews) } : item

/** Most recently viewed first. Items never viewed go last, by name. */
const byLastViewed = (a: SearchItem, b: SearchItem): number => {
    if (!a.lastViewedAt && !b.lastViewedAt) {
        return a.name.localeCompare(b.name)
    }
    if (!a.lastViewedAt) {
        return 1
    }
    if (!b.lastViewedAt) {
        return -1
    }
    return Date.parse(b.lastViewedAt) - Date.parse(a.lastViewedAt)
}

const visibleImports = (
    items: FileSystemImport[],
    featureFlags: FeatureFlagsSet,
    showUnreleased: boolean
): FileSystemImport[] =>
    items.filter(
        (item) =>
            (showUnreleased || item.category !== 'Unreleased') && isFileSystemImportFlagEnabled(item, featureFlags)
    )

const withUniqueHref = (items: FileSystemImport[]): FileSystemImport[] => {
    const seen = new Set<string>()
    return items.filter((item) => {
        if (!item.href || seen.has(item.href)) {
            return false
        }
        seen.add(item.href)
        return true
    })
}

const importToSearchItem = (
    item: FileSystemImport,
    fields: Pick<SearchItem, 'id' | 'category'> & Partial<SearchItem>
): SearchItem => ({
    name: item.path,
    displayName: item.path,
    productCategory: item.category || null,
    href: item.href || PLACEHOLDER_HREF,
    itemType: item.iconType || item.type || null,
    record: { type: item.type || item.iconType, iconType: item.iconType, iconColor: item.iconColor },
    ...fields,
})

const tabSearchItems = (
    parents: SearchItem[],
    sources: FileSystemImport[],
    featureFlags: FeatureFlagsSet
): SearchItem[] => {
    const tabsByPath = new Map(sources.map((source) => [source.path, source.searchTabs ?? []]))
    return parents.flatMap((parent) => {
        const parentName = parent.displayName || parent.name
        return (tabsByPath.get(parent.name) ?? [])
            .filter((tab) => isFileSystemImportFlagEnabled(tab, featureFlags))
            .map((tab) => ({
                id: `${parent.id}-tab-${tab.name}`,
                name: `${parentName} ${tab.name}`,
                displayName: tab.name,
                category: SEARCH_TAB_CATEGORY,
                parentName,
                href: tab.href,
                itemType: parent.itemType,
                searchKeywords: tab.searchKeywords,
                disabledReason: parent.disabledReason,
                record: parent.record,
            }))
    })
}

interface DestinationOptions {
    idPrefix: string
    category: string
    featureFlags: FeatureFlagsSet
    sceneViews: SceneViews
    extraItems?: SearchItem[]
}

const destinationSearchItems = (
    sources: FileSystemImport[],
    { idPrefix, category, featureFlags, sceneViews, extraItems = [] }: DestinationOptions
): SearchItem[] => {
    const items = [
        ...sources.map((source) =>
            importToSearchItem(source, {
                id: `${idPrefix}-${source.path}`,
                displayName: source.displayLabel ?? source.path,
                category,
                searchKeywords: [
                    ...(source.category ? (CATEGORY_SEARCH_KEYWORDS[source.category] ?? []) : []),
                    ...(source.searchKeywords ?? []),
                ],
                lastViewedAt: lastViewedAt(source.sceneKey, sceneViews),
                disabledReason: getProductAccessDisabledReason(source),
            })
        ),
        ...extraItems,
    ]
    return [...items, ...tabSearchItems(items, sources, featureFlags)].sort(byLastViewed)
}

/**
 * Format display name:
 * "Insight/Lifecycle" -> "New Lifecycle insight"
 * "Data/Destination" -> "New Destination" (no suffix for Data)
 */
const newItemDisplayName = (path: string): string => {
    const [kind, ...rest] = path.split('/')
    if (!rest.length) {
        return `New ${path}`
    }
    const suffix = kind.toLowerCase()
    return suffix === 'data' ? `New ${rest.join(' ')}` : `New ${rest.join(' ')} ${suffix}`
}

const APP_PRODUCT_ITEMS = [
    fixedItem('product-activity', 'Activity', 'tools', {
        href: urls.activity(ActivityTab.ExploreEvents),
        icon: <IconClock />,
        sceneKey: 'Activity',
        record: { type: 'activity' },
    }),
    fixedItem('product-exports', 'Exports', 'tools', {
        href: urls.exports(),
        icon: <IconDownload />,
        searchKeywords: ['downloads'],
        sceneKey: 'Exports',
        record: { type: 'exports' },
    }),
    fixedItem('product-subscriptions', 'Subscriptions', 'tools', {
        href: urls.subscriptions(),
        icon: <IconNotification />,
        searchKeywords: ['subscribe'],
        sceneKey: 'Subscriptions',
        record: { type: 'subscriptions' },
    }),
    // The user's own tickets with PostHog. The Support product holds tickets from their customers.
    fixedItem('misc-my-tickets', 'Your tickets', 'tools', {
        productCategory: 'PostHog support',
        href: urls.myTickets(),
        icon: <IconSupport />,
        itemType: 'my_tickets',
        searchKeywords: ['my tickets', 'support tickets', 'posthog support', 'contact support', 'support', 'help'],
        sceneKey: 'MyTickets',
        record: { type: 'my_tickets' },
    }),
]

// Blank SQL query in a new browser tab (inheriting the active warehouse connection when
// triggered from within the SQL editor). Scoped to the command palette: it relies on
// onSelect + newInternalTab, and only the 'command' Search surface honors onSelect —
// the new-tab scene and AI-first homepage are href-only and would render a dead item.
const NEW_SQL_QUERY_ITEM = fixedItem('new-sql-query-tab', 'New SQL query', 'create', {
    itemType: 'insight/hog',
    searchKeywords: ['sql', 'hogql', 'query', 'blank sql', 'new tab'],
    record: { type: 'insight', iconType: 'insight/hog' },
    onSelect: () => {
        const onSqlEditor = removeProjectIdIfPresent(router.values.location.pathname) === urls.sqlEditor()
        const connectionId = onSqlEditor ? router.values.hashParams?.c : undefined
        newInternalTab(urls.sqlEditor(connectionId ? { connectionId } : {}))
    },
})

const HEALTH_ITEMS = [
    fixedItem('health-overview', 'Health', 'health', {
        href: urls.health(),
        itemType: 'health',
        sceneKey: 'Health',
        record: { type: 'health', iconType: 'health' },
    }),
    fixedItem('health-pipeline-status', 'Pipeline status', 'health', {
        href: urls.pipelineStatus(),
        itemType: 'pipeline_status',
        sceneKey: 'PipelineStatus',
        record: { type: 'pipeline_status', iconType: 'pipeline_status' },
    }),
    fixedItem('health-sdk-health', 'SDK health', 'health', {
        href: urls.sdkHealth(),
        itemType: 'sdk_health',
        sceneKey: 'SdkHealth',
        record: { type: 'sdk_health', iconType: 'sdk_health' },
    }),
]

const terminalItem = (toggleTerminal: () => void): FixedSearchItem =>
    fixedItem('misc-toggle-terminal', 'Toggle terminal', 'actions', {
        icon: <IconTerminal />,
        searchKeywords: ['terminal', 'shell', 'console'],
        onSelect: toggleTerminal,
        record: { type: 'terminal' },
    })

const ACTION_ITEMS = [
    fixedItem('misc-logout', 'Log out', 'actions', {
        icon: <IconLeave />,
        searchKeywords: ['logout', 'log out', 'sign out', 'signout', 'exit'],
        onSelect: () => userLogic.actions.logout(),
        record: { type: 'logout' },
    }),
]

export const starredSearchItems = (entries: FileSystemEntry[]): SearchItem[] =>
    entries
        .filter((entry) => entry.type !== 'folder')
        .slice(0, STARRED_LIMIT)
        .map((entry) =>
            fileSystemEntryToSearchItem(entry, {
                id: `starred-${entry.id}`,
                category: 'starred',
                searchKeywords: ['starred', 'favorite', 'favourite', 'shortcut'],
            })
        )

export const productSearchItems = (
    featureFlags: FeatureFlagsSet,
    showUnreleased: boolean,
    sceneViews: SceneViews
): SearchItem[] => {
    const sources = withUniqueHref(
        visibleImports(
            [...getTreeItemsProducts(), ...getTreeItemsMetadata().filter((item) => !isDefinitionsTabHref(item.href))],
            featureFlags,
            showUnreleased
        )
    )
    return destinationSearchItems(sources, {
        idPrefix: 'product',
        category: 'tools',
        featureFlags,
        sceneViews,
        extraItems: APP_PRODUCT_ITEMS.map((item) => withLastViewed(item, sceneViews)),
    })
}

export const dataManagementSearchItems = (
    featureFlags: FeatureFlagsSet,
    showUnreleased: boolean,
    sceneViews: SceneViews
): SearchItem[] => {
    const sources = visibleImports(
        getTreeItemsMetadata().filter((item) => isDefinitionsTabHref(item.href)),
        featureFlags,
        showUnreleased
    )
    return destinationSearchItems(sources, {
        idPrefix: 'data-management',
        category: 'data-management',
        featureFlags,
        sceneViews,
    })
}

export const newSearchItems = (
    featureFlags: FeatureFlagsSet,
    showUnreleased: boolean,
    commandPalette: boolean
): SearchItem[] => [
    ...visibleImports(getTreeItemsNew(), featureFlags, showUnreleased).map((item) => {
        const displayName = newItemDisplayName(item.path)
        return importToSearchItem(item, {
            id: `new-${item.path}`,
            name: displayName,
            displayName,
            category: 'create',
            hiddenSearchText: [displayName, item.path, item.type, item.iconType].filter(Boolean).join(' '),
        })
    }),
    ...(commandPalette ? [NEW_SQL_QUERY_ITEM] : []),
]

export const peopleSearchItems = (groupItems: FileSystemImport[], sceneViews: SceneViews): SearchItem[] =>
    [...getDefaultTreePersons(), ...groupItems].map((item) =>
        importToSearchItem(item, {
            id: `people-${item.path}`,
            category: 'people',
            lastViewedAt: lastViewedAt(item.sceneKey, sceneViews),
        })
    )

export const healthSearchItems = (sceneViews: SceneViews): SearchItem[] =>
    HEALTH_ITEMS.map((item) => withLastViewed(item, sceneViews))

export const actionSearchItems = (toggleTerminal: (() => void) | null): SearchItem[] => [
    ...(toggleTerminal ? [terminalItem(toggleTerminal)] : []),
    ...ACTION_ITEMS,
]

/**
 * Lean projection of SETTINGS_MAP for search. The full map statically imports every
 * settings component (the whole configuration UI graph), so it is loaded dynamically
 * on mount and only the searchable metadata is kept.
 */
export interface SettingsSectionSummary {
    id: SettingSection['id']
    level: SettingSection['level']
    titleString: string | null
    hideFromNavigation?: boolean
    flag?: SettingSection['flag']
    to?: string
    keywords?: string[]
    settings: {
        id: string
        hasTitle: boolean
        titleString: string | null
        descriptionString: string | null
        keywords?: string[]
        flag?: SettingSection['flag']
    }[]
}

interface SettingsGates {
    isFlagEnabled: (flag: SettingSection['flag']) => boolean
    hasOrganizationIntegrations: boolean
    billingEntryUrl: string | null
}

const SHARED_SECTION_TITLES = new Set(['General', 'Danger zone', 'Integrations'])

const sentenceCaseId = (id: string): string => toSentenceCase(id.replace(/-/g, ' '))

const settingSearchTerms = (setting: SettingsSectionSummary['settings'][number]): string[] => [
    sentenceCaseId(setting.id),
    ...(setting.titleString ? [setting.titleString] : []),
    ...(setting.descriptionString ? [setting.descriptionString] : []),
    ...(setting.keywords ?? []),
]

// Sections hidden from navigation are only reachable from their product's own configuration page.
// Integrations and billing mirror the sidebar gates. billingEntryUrl is null when the user has no
// billing access, and for view-only members it points at Usage, which keeps them off the admin-only
// Overview and the restricted state it renders first.
const isSectionShown = (section: SettingsSectionSummary, gates: SettingsGates): boolean =>
    !section.hideFromNavigation &&
    gates.isFlagEnabled(section.flag) &&
    (section.id !== 'organization-integrations' || gates.hasOrganizationIntegrations) &&
    (section.id !== 'organization-billing' || !!gates.billingEntryUrl)

const toSettingsSearchItem = (section: SettingsSectionSummary, gates: SettingsGates): SearchItem => {
    // Environment sections show as project sections.
    const level = section.level === 'environment' ? 'project' : section.level
    const sectionId = section.id.replace(/^environment-/, 'project-') as SettingSectionId
    const levelName = toSentenceCase(level)
    const title = section.titleString ?? sentenceCaseId(section.id)
    const searchTerms = [
        ...(section.keywords ?? []),
        ...section.settings
            .filter((setting) => setting.hasTitle && gates.isFlagEnabled(setting.flag))
            .flatMap(settingSearchTerms),
    ]
    return {
        id: `settings-${sectionId}`,
        name: `${levelName}: ${title} (${searchTerms.join(',')})`,
        displayName: SHARED_SECTION_TITLES.has(title) ? `${title} (${levelName})` : title,
        category: 'settings',
        href:
            (section.id === 'organization-billing' && gates.billingEntryUrl) || section.to || urls.settings(sectionId),
        itemType: 'settings',
        record: { type: 'settings', level, sectionId },
    }
}

export const settingsSearchItems = (sections: SettingsSectionSummary[], gates: SettingsGates): SearchItem[] => {
    const items = new Map<string, SearchItem>()
    for (const section of sections) {
        if (!isSectionShown(section, gates)) {
            continue
        }
        const item = toSettingsSearchItem(section, gates)
        if (!items.has(item.id)) {
            items.set(item.id, item)
        }
    }
    return [...items.values()]
}

export interface CommandKSettingsSection {
    id: SettingSectionId
    level: Exclude<SettingLevelId, 'environment'>
    titleString: string | null
    to?: string
    keywords?: string[]
    settings: {
        id: SettingId
        titleString: string | null
        descriptionString: string | null
        keywords?: string[]
    }[]
}

const LEVEL_SEARCH_KEYWORDS: Partial<Record<CommandKSettingsSection['level'], string[]>> = {
    user: ['account settings', 'personal settings', 'my settings'],
}

const settingsItem = (
    id: string,
    name: string,
    href: string,
    record: Record<string, unknown>,
    fields: Partial<SearchItem> = {}
): SearchItem => ({
    id,
    name,
    displayName: name,
    category: 'settings',
    href,
    itemType: 'settings',
    hideMatchedKeyword: true,
    record: { type: 'settings', ...record },
    ...fields,
})

const settingsLevelName = (level: SettingLevelId): string =>
    `${toSentenceCase(level === 'environment' ? 'project' : level)} settings`

const settingsContextText = (level: SettingLevelId, sectionTitle: string): string =>
    `${settingsLevelName(level)} ${sectionTitle}`

interface SettingSearchTextSetting {
    id: string
    title: string | null
    keywords?: string[]
    description?: string | null
}

const settingsSearchText = (
    level: SettingLevelId,
    sectionTitle: string,
    sectionKeywords: string[] | undefined,
    settings: SettingSearchTextSetting[]
): string =>
    [
        settingsContextText(level, sectionTitle),
        ...(sectionKeywords ?? []),
        ...settings.flatMap((setting) => [
            setting.title ?? sentenceCaseId(setting.id),
            sentenceCaseId(setting.id),
            ...(setting.keywords ?? []),
            setting.description ?? '',
        ]),
    ]
        .filter(Boolean)
        .join(' ')

type SettingSummary = CommandKSettingsSection['settings'][number]

const textSetting = (setting: SettingSummary): SettingSearchTextSetting => ({
    id: setting.id,
    title: setting.titleString,
    keywords: setting.keywords,
    description: setting.descriptionString,
})

const commandKSectionSearchItems = (section: CommandKSettingsSection, billingEntryUrl: string | null): SearchItem[] => {
    const levelName = settingsLevelName(section.level)
    const title = section.titleString ?? sentenceCaseId(section.id)
    const context = settingsContextText(section.level, title)
    const ownsSettings = !section.to
    const settingTitle = (setting: SettingSummary): string => setting.titleString ?? sentenceCaseId(setting.id)
    const isOwnItem = (setting: SettingSummary): boolean =>
        ownsSettings && settingTitle(setting).toLowerCase() !== title.toLowerCase()
    const folded = section.settings.filter((setting) => !isOwnItem(setting))
    const sectionItem = settingsItem(
        `settings-${section.id}`,
        title,
        (section.id === 'organization-billing' && billingEntryUrl) || section.to || urls.settings(section.id),
        { level: section.level, sectionId: section.id },
        {
            parentName: levelName,
            searchKeywords: [
                context,
                ...(section.keywords ?? []),
                ...folded.flatMap((setting) => [sentenceCaseId(setting.id), ...(setting.keywords ?? [])]),
            ],
            hiddenSearchText: settingsSearchText(section.level, title, section.keywords, folded.map(textSetting)),
        }
    )
    return [
        sectionItem,
        ...section.settings.filter(isOwnItem).map((setting) =>
            settingsItem(
                `settings-${section.id}-${setting.id}`,
                settingTitle(setting),
                urls.settings(section.id, setting.id),
                { level: section.level, sectionId: section.id, settingId: setting.id },
                {
                    parentName: `${levelName} › ${title}`,
                    searchKeywords: [sentenceCaseId(setting.id), ...(setting.keywords ?? [])],
                    hiddenSearchText: settingsSearchText(section.level, title, section.keywords, [
                        textSetting(setting),
                    ]),
                }
            )
        ),
    ]
}

export const commandKSettingsSearchItems = (
    sections: CommandKSettingsSection[],
    billingEntryUrl: string | null
): SearchItem[] => {
    if (!sections.length) {
        return []
    }
    const levels = [...new Set(sections.map((section) => section.level))]
    const items = [
        settingsItem('settings', 'Settings', urls.settings(), {}, { searchKeywords: ['preferences', 'configuration'] }),
        ...levels.map((level) =>
            settingsItem(
                `settings-level-${level}`,
                settingsLevelName(level),
                urls.settings(level),
                { level },
                { searchKeywords: LEVEL_SEARCH_KEYWORDS[level] }
            )
        ),
        ...sections.flatMap((section) => commandKSectionSearchItems(section, billingEntryUrl)),
    ]
    return [...new Map(items.map((item) => [item.id, item])).values()]
}
