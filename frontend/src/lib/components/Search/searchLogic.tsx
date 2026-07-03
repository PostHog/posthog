import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { IconBell, IconClock, IconDownload, IconLeave, IconNotification } from '@posthog/icons'

import api from 'lib/api'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { GroupQueryResult, mapGroupQueryResponse } from 'lib/utils/groups'
import { toSentenceCase } from 'lib/utils/strings'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationIntegrationsLogic } from 'scenes/settings/organization/organizationIntegrationsLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { getDefaultTreePersons } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { groupsModel } from '~/models/groupsModel'
import { recentItemsModel } from '~/models/recentItemsModel'
import { getTreeItemsMetadata, getTreeItemsNew, getTreeItemsProducts } from '~/products'
import { FileSystemEntry, GroupsQueryResponse } from '~/queries/schema/schema-general'
import { matchesFlagDefinition } from '~/scenes/settings/flagGating'
import { Setting, SettingSection, SettingSectionId } from '~/scenes/settings/types'
import { ActivityTab, FileSystemIconColor, GroupTypeIndex, PersonType, SearchResponse } from '~/types'

import type { searchLogicType } from './searchLogicType'
import { filterSearchItems } from './utils'

let cachedProductIconColorByType: Map<string, FileSystemIconColor> | null = null
let cachedProductDisplayLabelByPath: Map<string, string> | null = null
let cachedProductIconTypeByPath: Map<string, string> | null = null

const getProductIconColorByType = (): Map<string, FileSystemIconColor> => {
    if (cachedProductIconColorByType === null) {
        cachedProductIconColorByType = new Map()
        for (const product of getTreeItemsProducts()) {
            const key = product.type || product.iconType
            if (key && product.iconColor) {
                cachedProductIconColorByType.set(key, product.iconColor)
            }
        }
    }
    return cachedProductIconColorByType
}

const getProductDisplayLabelByPath = (): Map<string, string> => {
    if (cachedProductDisplayLabelByPath === null) {
        cachedProductDisplayLabelByPath = new Map()
        for (const product of getTreeItemsProducts()) {
            if (product.displayLabel) {
                cachedProductDisplayLabelByPath.set(product.path, product.displayLabel)
            }
        }
    }
    return cachedProductDisplayLabelByPath
}

const getProductIconTypeByPath = (): Map<string, string> => {
    if (cachedProductIconTypeByPath === null) {
        cachedProductIconTypeByPath = new Map()
        for (const product of getTreeItemsProducts()) {
            const iconType = product.type || product.iconType
            if (iconType) {
                cachedProductIconTypeByPath.set(product.path, iconType)
            }
        }
    }
    return cachedProductIconTypeByPath
}

const fileSystemEntryToSearchItem = (
    item: FileSystemEntry,
    overrides: { id: string; category: string; searchKeywords?: string[] }
): SearchItem => {
    const name = splitPath(item.path).pop()
    const itemName = name ? unescapePath(name) : item.path
    const displayName = getProductDisplayLabelByPath().get(itemName)
    // Older starred shortcuts (e.g. Logs, Web analytics) were saved with a blank (empty-string)
    // type because their product only defines `iconType`. The `||` (not `??`) is deliberate: an
    // empty string must fall through to the product registry, keyed by name, so the icon resolves.
    const itemType = item.type || getProductIconTypeByPath().get(itemName) || null
    const productIconColor = itemType ? getProductIconColorByType().get(itemType) : undefined
    return {
        name: itemName,
        displayName,
        href: item.href || '#',
        lastViewedAt: item.last_viewed_at ?? null,
        itemType,
        record: { ...item, iconColor: productIconColor },
        ...overrides,
    }
}

// Types for command search results
export interface SearchItem {
    id: string
    name: string
    displayName?: string
    category: string
    productCategory?: string | null
    href?: string
    /** Action invoked when the item is selected. Use for items that trigger something
     * other than navigation (e.g. logging out). Consumers should prefer `onSelect` over `href`. */
    onSelect?: () => void
    icon?: React.ReactNode
    lastViewedAt?: string | null
    groupNoun?: string | null
    itemType?: string | null
    tags?: string[]
    searchKeywords?: string[]
    record?: Record<string, unknown>
    rank?: number | null // PostgreSQL full-text search rank (from unified search API)
}

export interface SearchCategory {
    key: string
    items: SearchItem[]
    isLoading: boolean
}

export interface SearchLogicProps {
    logicKey: string
}

export const RECENTS_LIMIT = 5
/** Max starred shortcuts shown in quick search (folders excluded). */
export const STARRED_LIMIT = 20
const SEARCH_LIMIT = 5

/** Safely extract a string — returns undefined for objects/arrays to avoid rendering [object Object]. */
const safeString = (val: unknown): string | undefined => (typeof val === 'string' ? val : undefined)

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
    settings: {
        id: string
        hasTitle: boolean
        titleString: string | null
        descriptionString: string | null
        keywords?: string[]
    }[]
}

export const searchLogic = kea<searchLogicType>([
    path((logicKey) => ['lib', 'components', 'Search', 'searchLogic', logicKey]),
    props({} as SearchLogicProps),
    key((props) => props.logicKey),
    connect(() => ({
        values: [
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            commandLogic,
            ['isCommandOpen'],
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['isDev'],
            userLogic,
            ['user'],
            recentItemsModel,
            ['recents as cachedRecents', 'recentsHasLoaded', 'sceneLogViewsByRef', 'sceneLogViewsHasLoaded'],
            projectTreeDataLogic,
            ['shortcutData as cachedStarred', 'shortcutDataHasLoaded', 'groupItems as treeGroupItems'],
            organizationIntegrationsLogic,
            ['organizationIntegrations'],
        ],
    })),
    actions({
        setSearch: (search: string) => ({ search }),
        setSettingsSections: (sections: SettingsSectionSummary[]) => ({ sections }),
    }),
    loaders(({ values }) => ({
        searchedRecents: [
            null as FileSystemEntry[] | null,
            {
                searchRecents: async ({ search }: { search: string }, breakpoint) => {
                    const searchTerm = search.trim()
                    if (!searchTerm) {
                        return null
                    }
                    const response = await api.fileSystem.list({
                        search: searchTerm,
                        limit: RECENTS_LIMIT + 1,
                        orderBy: '-last_viewed_at',
                        notType: 'folder',
                    })
                    breakpoint()
                    return response.results.slice(0, RECENTS_LIMIT)
                },
            },
        ],
        unifiedSearchResults: [
            null as SearchResponse | null,
            {
                loadUnifiedSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        return null
                    }

                    const response = await api.search.list({
                        q: trimmed,
                        include_counts: false,
                    })
                    breakpoint()

                    return response
                },
            },
        ],
        groupSearchResults: [
            {} as Partial<Record<GroupTypeIndex, GroupQueryResult[]>>,
            {
                loadGroupSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        return {}
                    }

                    const groupTypesList = Array.from(values.groupTypes.values())
                    if (groupTypesList.length === 0) {
                        return {}
                    }

                    const results = await Promise.allSettled(
                        groupTypesList.map((groupType) =>
                            api.groups.listClickhouse({
                                group_type_index: groupType.group_type_index,
                                search: trimmed,
                                limit: SEARCH_LIMIT,
                            })
                        )
                    )

                    breakpoint()

                    return Object.fromEntries(
                        results
                            .map((result, index) => [groupTypesList[index], result] as const)
                            .filter(([, result]) => result.status === 'fulfilled')
                            .map(([groupType, result]) => [
                                groupType.group_type_index,
                                mapGroupQueryResponse((result as PromiseFulfilledResult<GroupsQueryResponse>).value),
                            ])
                    ) as Record<GroupTypeIndex, GroupQueryResult[]>
                },
            },
        ],
        personSearchResults: [
            [] as PersonType[],
            {
                loadPersonSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        return []
                    }

                    const response = await api.persons.list({ search: trimmed, limit: SEARCH_LIMIT })
                    breakpoint()

                    return response.results
                },
            },
        ],
        playlistSearchResults: [
            [] as FileSystemEntry[],
            {
                loadPlaylistSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        return []
                    }

                    const response = await api.fileSystem.list({
                        search: trimmed,
                        type: 'session_recording_playlist',
                        limit: SEARCH_LIMIT,
                    })
                    breakpoint()

                    return response.results
                },
            },
        ],
    })),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
            },
        ],
        searchPending: [
            false,
            {
                setSearch: (_, { search }) => search.trim() !== '',
                loadUnifiedSearchResultsSuccess: () => false,
                loadUnifiedSearchResultsFailure: () => false,
            },
        ],
        settingsSections: [
            [] as SettingsSectionSummary[],
            {
                setSettingsSections: (_, { sections }) => sections,
            },
        ],
    }),
    selectors({
        isSearching: [
            (s) => [
                s.searchedRecentsLoading,
                s.unifiedSearchResultsLoading,
                s.groupSearchResultsLoading,
                s.personSearchResultsLoading,
                s.playlistSearchResultsLoading,
                s.searchPending,
                s.search,
            ],
            (
                searchedRecentsLoading: boolean,
                unifiedSearchResultsLoading: boolean,
                groupSearchResultsLoading: boolean,
                personSearchResultsLoading: boolean,
                playlistSearchResultsLoading: boolean,
                searchPending: boolean,
                search: string
            ): boolean =>
                (searchedRecentsLoading ||
                    unifiedSearchResultsLoading ||
                    groupSearchResultsLoading ||
                    personSearchResultsLoading ||
                    playlistSearchResultsLoading ||
                    searchPending) &&
                search.trim() !== '',
        ],
        recentItems: [
            (s) => [s.searchedRecents, s.cachedRecents, s.search],
            (searchedRecents, cachedRecents, search): SearchItem[] => {
                const source = search.trim() ? (searchedRecents ?? []) : cachedRecents.slice(0, RECENTS_LIMIT)
                return source.map((item) => fileSystemEntryToSearchItem(item, { id: item.path, category: 'recents' }))
            },
        ],
        starredItems: [
            (s) => [s.cachedStarred],
            (cachedStarred): SearchItem[] => {
                return cachedStarred
                    .filter((e) => e.type !== 'folder')
                    .slice(0, STARRED_LIMIT)
                    .map((item) =>
                        fileSystemEntryToSearchItem(item, {
                            id: `starred-${item.id}`,
                            category: 'starred',
                            searchKeywords: ['starred', 'favorite', 'favourite', 'shortcut'],
                        })
                    )
            },
        ],
        toolsItems: [
            (s) => [s.featureFlags, s.isDev, s.user, s.sceneLogViewsByRef],
            (featureFlags, isDev, user, sceneLogViewsByRef): SearchItem[] => {
                const allProducts = getTreeItemsProducts()
                const filteredProducts = allProducts.filter((product) => {
                    if (!product.href) {
                        return false
                    }
                    if (!isDev && !user?.is_staff && product.category === 'Unreleased') {
                        return false
                    }
                    if (product.flag && !(featureFlags as Record<string, boolean>)[product.flag]) {
                        return false
                    }
                    return true
                })

                const items: SearchItem[] = filteredProducts.map((product) => ({
                    id: `app-${product.path}`,
                    name: product.path,
                    displayName: product.displayLabel ?? product.path,
                    category: 'tools',
                    productCategory: product.category || null,
                    href: product.href || '#',
                    itemType: product.iconType || product.type || null,
                    tags: product.tags,
                    lastViewedAt: product.sceneKey ? (sceneLogViewsByRef[product.sceneKey] ?? null) : null,
                    record: {
                        type: product.type || product.iconType,
                        iconType: product.iconType,
                        iconColor: product.iconColor,
                    },
                }))
                items.push({
                    id: 'app-activity',
                    name: 'Activity',
                    displayName: 'Activity',
                    category: 'tools',
                    productCategory: null,
                    href: urls.activity(ActivityTab.ExploreEvents),
                    icon: <IconClock />,
                    itemType: null,
                    tags: undefined,
                    lastViewedAt: sceneLogViewsByRef['Activity'] ?? null,
                    record: {
                        type: 'activity',
                        iconType: undefined,
                        iconColor: undefined,
                    },
                })

                // Sort by lastViewedAt (most recent first), items without lastViewedAt go to the end
                return items.sort((a, b) => {
                    if (!a.lastViewedAt && !b.lastViewedAt) {
                        return a.name.localeCompare(b.name)
                    }
                    if (!a.lastViewedAt) {
                        return 1
                    }
                    if (!b.lastViewedAt) {
                        return -1
                    }
                    return new Date(b.lastViewedAt).getTime() - new Date(a.lastViewedAt).getTime()
                })
            },
        ],
        dataManagementItems: [
            (s) => [s.featureFlags, s.isDev, s.user, s.sceneLogViewsByRef],
            (featureFlags, isDev, user, sceneLogViewsByRef): SearchItem[] => {
                const allMetadata = getTreeItemsMetadata()
                const filteredMetadata = allMetadata.filter((item) => {
                    if (!isDev && !user?.is_staff && item.category === 'Unreleased') {
                        return false
                    }
                    if (item.flag && !(featureFlags as Record<string, boolean>)[item.flag]) {
                        return false
                    }
                    return true
                })

                const categorySearchKeywords: Record<string, string[]> = {
                    Pipeline: ['data pipelines', 'data pipeline'],
                }

                const items = filteredMetadata.map((item) => ({
                    id: `data-management-${item.path}`,
                    name: item.path,
                    displayName: item.path,
                    category: 'data-management',
                    productCategory: item.category || null,
                    href: item.href || '#',
                    itemType: item.iconType || item.type || null,
                    tags: item.tags,
                    searchKeywords: item.category ? categorySearchKeywords[item.category] : undefined,
                    lastViewedAt: item.sceneKey ? (sceneLogViewsByRef[item.sceneKey] ?? null) : null,
                    record: {
                        type: item.type || item.iconType,
                        iconType: item.iconType,
                        iconColor: item.iconColor,
                    },
                }))

                // Sort by lastViewedAt (most recent first), items without lastViewedAt go to the end
                return items.sort((a, b) => {
                    if (!a.lastViewedAt && !b.lastViewedAt) {
                        return a.name.localeCompare(b.name)
                    }
                    if (!a.lastViewedAt) {
                        return 1
                    }
                    if (!b.lastViewedAt) {
                        return -1
                    }
                    return new Date(b.lastViewedAt).getTime() - new Date(a.lastViewedAt).getTime()
                })
            },
        ],
        newItems: [
            (s) => [s.featureFlags, s.isDev, s.user],
            (featureFlags, isDev, user): SearchItem[] => {
                const allNewItems = getTreeItemsNew()
                const filteredItems = allNewItems.filter((item) => {
                    if (!isDev && !user?.is_staff && item.category === 'Unreleased') {
                        return false
                    }
                    if (item.flag && !(featureFlags as Record<string, boolean>)[item.flag]) {
                        return false
                    }
                    return true
                })

                return filteredItems.map((item) => {
                    // Format display name:
                    // "Insight/Lifecycle" -> "New Lifecycle insight"
                    // "Data/Destination" -> "New Destination" (no suffix for Data)
                    const pathParts = item.path.split('/')
                    let displayName: string
                    if (pathParts.length > 1) {
                        const suffix = pathParts[0].toLowerCase()
                        // Don't append "data" suffix for data pipeline items
                        displayName =
                            suffix === 'data'
                                ? `New ${pathParts.slice(1).join(' ')}`
                                : `New ${pathParts.slice(1).join(' ')} ${suffix}`
                    } else {
                        displayName = `New ${item.path}`
                    }

                    return {
                        id: `new-${item.path}`,
                        name: displayName,
                        displayName,
                        category: 'create',
                        productCategory: item.category || null,
                        href: item.href || '#',
                        itemType: item.iconType || item.type || null,
                        tags: item.tags,
                        record: {
                            type: item.type || item.iconType,
                            iconType: item.iconType,
                            iconColor: item.iconColor,
                        },
                    }
                })
            },
        ],
        peopleItems: [
            (s) => [s.treeGroupItems, s.sceneLogViewsByRef],
            (treeGroupItems, sceneLogViewsByRef): SearchItem[] => {
                const combined = [...getDefaultTreePersons(), ...treeGroupItems]
                return combined.map((item) => ({
                    id: `people-${item.path}`,
                    name: item.path,
                    displayName: item.path,
                    category: 'people',
                    productCategory: item.category || null,
                    href: item.href || '#',
                    itemType: item.iconType || item.type || null,
                    tags: item.tags,
                    lastViewedAt: item.sceneKey ? (sceneLogViewsByRef[item.sceneKey] ?? null) : null,
                    record: {
                        type: item.type || item.iconType,
                        iconType: item.iconType,
                        iconColor: item.iconColor,
                    },
                }))
            },
        ],
        groupItems: [
            (s) => [s.groupSearchResults, s.aggregationLabel],
            (groupSearchResults, aggregationLabel): SearchItem[] => {
                const items: SearchItem[] = []
                for (const [groupTypeIndexString, groups] of Object.entries(groupSearchResults)) {
                    const groupTypeIndex = parseInt(groupTypeIndexString, 10) as GroupTypeIndex
                    const noun = aggregationLabel(groupTypeIndex).singular
                    ;(groups as GroupQueryResult[]).forEach((group) => {
                        const display = group.group_properties?.name || group.group_key || String(group.group_key)
                        items.push({
                            id: `group-${groupTypeIndex}-${group.group_key}`,
                            name: `${noun}: ${display}`,
                            displayName: display,
                            category: 'groups',
                            href: `/groups/${groupTypeIndex}/${encodeURIComponent(group.group_key)}`,
                            groupNoun: noun,
                            itemType: 'group',
                            record: {
                                type: 'group',
                                groupTypeIndex,
                                groupKey: group.group_key,
                                groupNoun: noun,
                            },
                        })
                    })
                }
                return items
            },
        ],
        personItems: [
            (s) => [s.personSearchResults],
            (personSearchResults): SearchItem[] => {
                return personSearchResults
                    .filter((person) => person.uuid) // Skip persons without uuid to avoid invalid URLs
                    .map((person) => {
                        const personId = person.distinct_ids?.[0] || person.uuid
                        const displayName =
                            safeString(person.properties?.email) ||
                            safeString(person.properties?.name) ||
                            String(personId)

                        return {
                            id: `person-${person.uuid}`,
                            name: displayName,
                            displayName,
                            category: 'persons',
                            href: urls.personByUUID(person.uuid!),
                            itemType: 'person',
                            record: {
                                type: 'person',
                                uuid: person.uuid,
                                distinctIds: person.distinct_ids,
                            },
                        }
                    })
            },
        ],
        playlistItems: [
            (s) => [s.playlistSearchResults],
            (playlistSearchResults): SearchItem[] => {
                return playlistSearchResults.map((item) => {
                    const name = splitPath(item.path).pop()
                    return {
                        id: `playlist-${item.id}`,
                        name: name ? unescapePath(name) : item.path,
                        category: 'session_recording_playlist',
                        href: item.href || '#',
                        itemType: 'session_recording_playlist',
                        record: item as unknown as Record<string, unknown>,
                    }
                })
            },
        ],
        healthItems: [
            (s) => [s.sceneLogViewsByRef],
            (sceneLogViewsByRef): SearchItem[] => [
                {
                    id: 'health-pipeline-status',
                    name: 'Pipeline status',
                    displayName: 'Pipeline status',
                    category: 'health',
                    href: urls.pipelineStatus(),
                    itemType: 'pipeline_status',
                    lastViewedAt: sceneLogViewsByRef['PipelineStatus'] ?? null,
                    record: { type: 'pipeline_status', iconType: 'pipeline_status' },
                },
                {
                    id: 'health-sdk-health',
                    name: 'SDK health',
                    displayName: 'SDK health',
                    category: 'health',
                    href: urls.sdkHealth(),
                    itemType: 'sdk_health',
                    lastViewedAt: sceneLogViewsByRef['SdkHealth'] ?? null,
                    record: { type: 'sdk_health', iconType: 'sdk_health' },
                },
            ],
        ],
        miscItems: [
            (s) => [s.sceneLogViewsByRef],
            (sceneLogViewsByRef): SearchItem[] => [
                {
                    id: 'misc-exports',
                    name: 'Exports',
                    displayName: 'Exports',
                    category: 'misc',
                    href: urls.exports(),
                    icon: <IconDownload />,
                    itemType: null,
                    lastViewedAt: sceneLogViewsByRef['Exports'] ?? null,
                    record: { type: 'exports' },
                },
                {
                    id: 'misc-alerts',
                    name: 'Alerts',
                    displayName: 'Alerts',
                    category: 'misc',
                    href: urls.alerts(),
                    icon: <IconBell />,
                    itemType: null,
                    lastViewedAt: sceneLogViewsByRef['SavedInsights'] ?? null,
                    record: { type: 'alerts' },
                },
                {
                    id: 'misc-subscriptions',
                    name: 'Subscriptions',
                    displayName: 'Subscriptions',
                    category: 'misc',
                    href: urls.subscriptions(),
                    icon: <IconNotification />,
                    itemType: null,
                    lastViewedAt: sceneLogViewsByRef['Subscriptions'] ?? null,
                    record: { type: 'subscriptions' },
                },
                {
                    id: 'misc-logout',
                    name: 'Log out',
                    displayName: 'Log out',
                    category: 'misc',
                    icon: <IconLeave />,
                    itemType: null,
                    searchKeywords: ['logout', 'log out', 'sign out', 'signout', 'exit'],
                    onSelect: () => userLogic.actions.logout(),
                    record: { type: 'logout' },
                },
            ],
        ],
        settingsItems: [
            (s) => [s.featureFlags, s.organizationIntegrations, s.settingsSections],
            (featureFlags, organizationIntegrations, settingsSections): SearchItem[] => {
                const checkFlag = (flagKey: Pick<Setting, 'flag'>['flag']): boolean =>
                    matchesFlagDefinition(flagKey, featureFlags)

                const items: SearchItem[] = []

                // Skip project-level sections as they are duplicates of environment sections
                const seenSectionIds = new Set<string>()

                for (const section of settingsSections) {
                    // Skip sections hidden from navigation (they are only accessible
                    // from their product's own configuration page)
                    if (section.hideFromNavigation) {
                        continue
                    }

                    // Mirror sidebar gating: only surface organization integrations when any exist
                    if (
                        section.id === 'organization-integrations' &&
                        (!organizationIntegrations || organizationIntegrations.length === 0)
                    ) {
                        continue
                    }

                    // Map environment sections to project level
                    const effectiveLevel = section.level === 'environment' ? 'project' : section.level
                    const effectiveSectionId = (
                        section.level === 'environment' ? section.id.replace('environment-', 'project-') : section.id
                    ) as SettingSectionId

                    // Skip duplicate project sections (environment sections take priority)
                    if (seenSectionIds.has(effectiveSectionId)) {
                        continue
                    }
                    seenSectionIds.add(effectiveSectionId)

                    // Filter by feature flag if required
                    if (section.flag) {
                        if (!checkFlag(section.flag as Pick<Setting, 'flag'>['flag'])) {
                            continue
                        }
                    }

                    // Create a search item for each settings section
                    const levelPrefix = toSentenceCase(effectiveLevel)

                    const settings = section.settings
                        .filter((setting) => setting.hasTitle)
                        .flatMap((setting) => [
                            toSentenceCase(setting.id.replace(/[-]/g, ' ')),
                            ...(setting.titleString ? [setting.titleString] : []),
                            ...(setting.descriptionString ? [setting.descriptionString] : []),
                            ...(setting.keywords ?? []),
                        ])

                    // Create the display name for each settings section
                    const displayName = section.titleString ?? toSentenceCase(section.id.replace(/[-]/g, ' '))

                    const displayNameSuffix =
                        displayName === 'General' || displayName === 'Danger zone' || displayName === 'Integrations'
                            ? ` (${toSentenceCase(effectiveLevel)})`
                            : ''

                    items.push({
                        id: `settings-${effectiveSectionId}`,
                        name: `${levelPrefix}: ${displayName} (${settings})`,
                        displayName: `${displayName}${displayNameSuffix}`,
                        category: 'settings',
                        href: section.to || urls.settings(effectiveSectionId),
                        itemType: 'settings',
                        record: {
                            type: 'settings',
                            level: effectiveLevel,
                            sectionId: effectiveSectionId,
                        },
                    })
                }

                return items
            },
        ],
        unifiedSearchItems: [
            (s) => [s.unifiedSearchResults],
            (unifiedSearchResults): Record<string, SearchItem[]> => {
                if (!unifiedSearchResults) {
                    return {}
                }

                const categoryItems: Record<string, SearchItem[]> = {}

                for (const result of unifiedSearchResults.results) {
                    const category = result.type
                    if (!categoryItems[category]) {
                        categoryItems[category] = []
                    }

                    let name = result.result_id
                    let href = ''

                    switch (result.type) {
                        case 'insight':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/insights/${result.result_id}`
                            break
                        case 'dashboard':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/dashboard/${result.result_id}`
                            break
                        case 'feature_flag':
                            name = safeString(result.extra_fields.key) || result.result_id
                            href = `/feature_flags/${result.result_id}`
                            break
                        case 'experiment':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/experiments/${result.result_id}`
                            break
                        case 'early_access_feature':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/early_access_features/${result.result_id}`
                            break
                        case 'hog_flow':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/workflows/${result.result_id}/workflow`
                            break
                        case 'survey':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/surveys/${result.result_id}`
                            break
                        case 'notebook':
                            name = safeString(result.extra_fields.title) || result.result_id
                            href = `/notebooks/${result.result_id}`
                            break
                        case 'cohort':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/cohorts/${result.result_id}`
                            break
                        case 'action':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/data-management/actions/${result.result_id}`
                            break
                        case 'event_definition':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/data-management/events/${result.result_id}`
                            break
                        case 'property_definition':
                            name = safeString(result.extra_fields.name) || result.result_id
                            href = `/data-management/properties/${result.result_id}`
                            break
                    }

                    categoryItems[category].push({
                        id: `${result.type}-${result.result_id}`,
                        name,
                        category,
                        href,
                        itemType: result.type,
                        rank: result.rank,
                        record: {
                            type: result.type,
                            ...result.extra_fields,
                        },
                    })
                }

                return categoryItems
            },
        ],
        loadingStates: [
            (s) => [
                s.unifiedSearchResultsLoading,
                s.recentsHasLoaded,
                s.shortcutDataHasLoaded,
                s.sceneLogViewsHasLoaded,
                s.personSearchResultsLoading,
                s.groupSearchResultsLoading,
                s.playlistSearchResultsLoading,
            ],
            (
                unifiedSearchResultsLoading: boolean,
                recentsHasLoaded: boolean,
                shortcutDataHasLoaded: boolean,
                sceneLogViewsHasLoaded: boolean,
                personSearchResultsLoading: boolean,
                groupSearchResultsLoading: boolean,
                playlistSearchResultsLoading: boolean
            ) => ({
                unifiedSearchResultsLoading,
                recentsLoading: !recentsHasLoaded,
                recentsHasLoaded,
                starredLoading: !shortcutDataHasLoaded,
                starredHasLoaded: shortcutDataHasLoaded,
                isToolsLoading: !sceneLogViewsHasLoaded,
                personSearchResultsLoading,
                groupSearchResultsLoading,
                playlistSearchResultsLoading,
            }),
        ],
        allCategories: [
            (s) => [
                s.recentItems,
                s.starredItems,
                s.toolsItems,
                s.dataManagementItems,
                s.peopleItems,
                s.healthItems,
                s.miscItems,
                s.settingsItems,
                s.newItems,
                s.personItems,
                s.groupItems,
                s.playlistItems,
                s.unifiedSearchItems,
                s.loadingStates,
                s.search,
            ],
            (
                recentItems: SearchItem[],
                starredItems: SearchItem[],
                toolsItems: SearchItem[],
                dataManagementItems: SearchItem[],
                peopleItems: SearchItem[],
                healthItems: SearchItem[],
                miscItems: SearchItem[],
                settingsItems: SearchItem[],
                newItems: SearchItem[],
                personItems: SearchItem[],
                groupItems: SearchItem[],
                playlistItems: SearchItem[],
                unifiedSearchItems: Record<string, SearchItem[]>,
                loadingStates: {
                    unifiedSearchResultsLoading: boolean
                    recentsLoading: boolean
                    recentsHasLoaded: boolean
                    starredLoading: boolean
                    starredHasLoaded: boolean
                    isToolsLoading: boolean
                    personSearchResultsLoading: boolean
                    groupSearchResultsLoading: boolean
                    playlistSearchResultsLoading: boolean
                },
                search: string
            ): SearchCategory[] => {
                const {
                    unifiedSearchResultsLoading,
                    recentsLoading,
                    recentsHasLoaded,
                    starredLoading,
                    starredHasLoaded,
                    isToolsLoading,
                    personSearchResultsLoading,
                    groupSearchResultsLoading,
                    playlistSearchResultsLoading,
                } = loadingStates

                const categories: SearchCategory[] = []
                const hasSearch = search.trim() !== ''

                // Filter items by search term using Fuse.js fuzzy search
                const filterBySearch = (items: SearchItem[]): SearchItem[] => {
                    if (!hasSearch) {
                        return items
                    }
                    return filterSearchItems(items, search)
                }

                // Always show recents first - show loading skeleton until first load completes
                const isRecentsLoading = recentsLoading || !recentsHasLoaded
                categories.push({
                    key: 'recents',
                    items: recentItems,
                    isLoading: isRecentsLoading,
                })

                const isStarredLoading = starredLoading || !starredHasLoaded
                categories.push({
                    key: 'starred',
                    items: starredItems,
                    isLoading: isStarredLoading,
                })

                // Filter tools and data management by search
                const filteredTools = filterBySearch(toolsItems)
                const filteredDataManagement = filterBySearch(dataManagementItems)

                // Show tools if not searching or has matching results
                if (!hasSearch || filteredTools.length > 0) {
                    categories.push({
                        key: 'tools',
                        items: isToolsLoading ? [] : filteredTools,
                        isLoading: isToolsLoading,
                    })
                }

                // Show data management if not searching or has matching results
                if (!hasSearch || filteredDataManagement.length > 0) {
                    categories.push({
                        key: 'data-management',
                        items: isToolsLoading ? [] : filteredDataManagement,
                        isLoading: isToolsLoading,
                    })
                }

                // Show people items (persons, cohorts, group types) if searching with matching results
                const filteredPeople = filterBySearch(peopleItems)
                if (hasSearch && filteredPeople.length > 0) {
                    categories.push({
                        key: 'people',
                        items: filteredPeople,
                        isLoading: false,
                    })
                }

                // Show health items if searching with matching results
                const filteredHealth = filterBySearch(healthItems)
                if (hasSearch && filteredHealth.length > 0) {
                    categories.push({
                        key: 'health',
                        items: filteredHealth,
                        isLoading: false,
                    })
                }

                // Show misc items if searching with matching results
                const filteredMisc = filterBySearch(miscItems)
                if (hasSearch && filteredMisc.length > 0) {
                    categories.push({
                        key: 'misc',
                        items: filteredMisc,
                        isLoading: false,
                    })
                }

                // Filter and show settings if searching with matching results
                const filteredSettings = filterBySearch(settingsItems)
                if (hasSearch && filteredSettings.length > 0) {
                    categories.push({
                        key: 'settings',
                        items: filteredSettings,
                        isLoading: false,
                    })
                }

                // Show "create" category only when searching and matching "new" or relevant keywords
                if (hasSearch) {
                    const searchLower = search.toLowerCase()
                    const searchChunks = searchLower.split(' ').filter((s) => s)

                    // Filter new items - ALL search chunks must match
                    const filteredNewItems = newItems.filter((item) => {
                        const nameLower = (item.displayName || item.name || '').toLowerCase()
                        const typeLower = (item.itemType || '').toLowerCase()
                        // Also search against the original path (stored in id as "new-{path}")
                        const idLower = item.id.toLowerCase()

                        // Every chunk must match either "new"/"create" or be found in the item name/type/id
                        return searchChunks.every((chunk) => {
                            if (
                                chunk === 'new' ||
                                chunk === 'create' ||
                                chunk.startsWith('new') ||
                                chunk.startsWith('create')
                            ) {
                                return true
                            }
                            if (nameLower.includes(chunk)) {
                                return true
                            }
                            if (typeLower.includes(chunk)) {
                                return true
                            }
                            if (idLower.includes(chunk)) {
                                return true
                            }
                            return false
                        })
                    })

                    if (filteredNewItems.length > 0) {
                        categories.push({
                            key: 'create',
                            items: filteredNewItems,
                            isLoading: false,
                        })
                    }
                }

                // Only show unified search results when searching
                if (hasSearch) {
                    const unifiedLoading = unifiedSearchResultsLoading

                    // Add unified search categories
                    const categoryOrder = [
                        'insight',
                        'dashboard',
                        'feature_flag',
                        'experiment',
                        'early_access_feature',
                        'survey',
                        'notebook',
                        'cohort',
                        'action',
                        'event_definition',
                        'property_definition',
                        'hog_flow',
                    ]

                    for (const category of categoryOrder) {
                        const items = unifiedSearchItems[category] || []
                        if (items.length > 0 || unifiedLoading) {
                            categories.push({
                                key: category,
                                items,
                                isLoading: unifiedLoading && items.length === 0,
                            })
                        }
                    }

                    // Add session recording playlists
                    if (playlistItems.length > 0 || playlistSearchResultsLoading) {
                        categories.push({
                            key: 'session_recording_playlist',
                            items: playlistItems,
                            isLoading: playlistSearchResultsLoading,
                        })
                    }

                    // Add persons
                    if (personItems.length > 0 || personSearchResultsLoading) {
                        categories.push({
                            key: 'persons',
                            items: personItems,
                            isLoading: personSearchResultsLoading,
                        })
                    }

                    // Add groups
                    if (groupItems.length > 0 || groupSearchResultsLoading) {
                        categories.push({
                            key: 'groups',
                            items: groupItems,
                            isLoading: groupSearchResultsLoading,
                        })
                    }
                }

                return categories
            },
        ],
    }),
    listeners(({ actions }) => ({
        setSearch: async ({ search }, breakpoint) => {
            await breakpoint(150)

            if (search.trim() !== '') {
                actions.searchRecents({ search })
                actions.loadUnifiedSearchResults({ searchTerm: search })
                actions.loadPersonSearchResults({ searchTerm: search })
                actions.loadGroupSearchResults({ searchTerm: search })
                actions.loadPlaylistSearchResults({ searchTerm: search })
            }
        },
    })),
    afterMount(({ actions }) => {
        import('~/scenes/settings/SettingsMap')
            .then(({ SETTINGS_MAP }) => {
                actions.setSettingsSections(
                    SETTINGS_MAP.map((section) => ({
                        id: section.id,
                        level: section.level,
                        titleString: typeof section.title === 'string' ? section.title : null,
                        hideFromNavigation: section.hideFromNavigation,
                        flag: section.flag,
                        to: section.to,
                        settings: section.settings.map((setting) => ({
                            id: setting.id,
                            // A JSX-titled setting has no title string to search but must stay
                            // findable via its id token — hasTitle preserves that distinction.
                            hasTitle: !!setting.title,
                            titleString: typeof setting.title === 'string' ? setting.title : null,
                            descriptionString: typeof setting.description === 'string' ? setting.description : null,
                            keywords: setting.keywords,
                        })),
                    }))
                )
            })
            .catch((error) => {
                console.error('Failed to load SETTINGS_MAP for settings search:', error)
            })
    }),
])
