import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { hogql } from 'lib/utils/hogql'
import { isUnderPath, removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'
import { Noun, groupsModel } from '~/models/groupsModel'
import { GroupTab, groupTabs as groupTabsFor } from '~/models/groupTabs'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { GroupType, GroupTypeIndex, TeamPublicType, TeamType } from '~/types'

import { cohortsList } from 'products/cohorts/frontend/generated/api'
import { accountsList, customerJourneysList } from 'products/customer_analytics/frontend/generated/api'

import { matchesPaneQuery } from './todayPaneSearch'
import { TodayPeoplePin, TodayPeopleRecent, peoplePinsFromShortcuts, peopleRecentRowKey } from './todayPeople'
import { todayPeopleRecentsLogic } from './todayPeopleRecentsLogic'
import {
    TODAY_PEOPLE_ROWS,
    TODAY_PEOPLE_ROW_SECTION_LABELS,
    TodayPeopleRowSection,
    TodayPeopleSection,
    TodayPeopleStaticRowKey,
} from './todayPeopleRows'
import { TODAY_USER_PERSIST_OPTIONS } from './todayUserPersistOptions'

/** A section under Recents with its rows, in pane order. */
export interface TodayPeopleRowSectionGroup {
    key: TodayPeopleRowSection
    label: string
    rows: TodayPeopleRow[]
}

function rowSection(row: TodayPeopleRow): TodayPeopleRowSection | null {
    return row.kind === 'group' ? 'groups' : TODAY_PEOPLE_ROWS[row.key].section
}

export type TodayPeopleRowCounts = Partial<Record<'accounts' | 'cohorts' | 'journeys', number>>

export type TodayPeopleGroupRowKey = `groups-${number}`

// pinned: the row ids. Each one is part of the row's `people-sidebar-<row>` data-attr.
export type TodayPeopleRowKey = TodayPeopleStaticRowKey | TodayPeopleGroupRowKey

interface TodayPeopleRowBase {
    label: string
    href: string
    /** The paths that mark the row active. */
    paths: string[]
}

export type TodayPeopleRow =
    | (TodayPeopleRowBase & { kind: 'static'; key: TodayPeopleStaticRowKey })
    | (TodayPeopleRowBase & { kind: 'group'; key: TodayPeopleGroupRowKey })

export function accountGroupTypeIndex(
    configuredIndex: number | null | undefined,
    groupTypes: Map<GroupTypeIndex, GroupType>
): GroupTypeIndex | null {
    if (configuredIndex != null && groupTypes.has(configuredIndex as GroupTypeIndex)) {
        return configuredIndex as GroupTypeIndex
    }
    const [first] = [...groupTypes.keys()].sort((a, b) => a - b)
    return first ?? null
}

function staticRow(key: TodayPeopleStaticRowKey, href?: string, paths?: string[]): TodayPeopleRow {
    const definition = TODAY_PEOPLE_ROWS[key]
    const rowHref = href ?? definition.href()
    const rowPaths = paths ?? ('paths' in definition ? definition.paths() : [rowHref])
    return { kind: 'static', key, label: definition.label, href: rowHref, paths: rowPaths }
}

/**
 * The Accounts row and the group type rows. Accounts is a Customer analytics idea, so without that flag every group
 * type keeps its own name. With it there is one Accounts row: the Customer analytics accounts page with
 * customer-analytics-csp, which also covers the account group type's pages, else the account group type itself.
 */
function accountAndGroupRows(
    featureFlags: FeatureFlagsSet,
    groupTypeIndex: GroupTypeIndex | null,
    groupTabs: GroupTab[]
): TodayPeopleRow[] {
    const customerAnalytics = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS]
    const accountsPage = TODAY_PEOPLE_ROWS.accounts.enabled(featureFlags)
    const accountTab = customerAnalytics ? groupTabs.find((tab) => tab.key === `groups-${groupTypeIndex}`) : undefined
    const accounts = accountsPage
        ? staticRow('accounts', undefined, [urls.customerAnalyticsAccounts(), ...(accountTab ? [accountTab.url] : [])])
        : accountTab
          ? staticRow('accounts', accountTab.url)
          : null
    const groups = groupTabs
        .filter((tab) => tab !== accountTab)
        .map(
            (tab): TodayPeopleRow => ({
                kind: 'group',
                key: tab.key,
                label: tab.label,
                href: tab.url,
                paths: [tab.url],
            })
        )
    return [...(accounts ? [accounts] : []), ...groups]
}

/**
 * The People pane rows in pane order: the rows of `TODAY_PEOPLE_ROWS` that are on, with the group types after
 * Accounts. They carry the Customer analytics tabs, which this shell hides, so the tab bars on those pages can go.
 */
export function peopleSidebarRows(
    featureFlags: FeatureFlagsSet,
    groupTypeIndex: GroupTypeIndex | null,
    groupTabs: GroupTab[] = []
): TodayPeopleRow[] {
    return (Object.keys(TODAY_PEOPLE_ROWS) as TodayPeopleStaticRowKey[]).flatMap((key) =>
        key === 'accounts'
            ? accountAndGroupRows(featureFlags, groupTypeIndex, groupTabs)
            : TODAY_PEOPLE_ROWS[key].enabled(featureFlags)
              ? [staticRow(key)]
              : []
    )
}

/** The sections under Recents, in pane order. A section with no rows is left out. */
export function peopleRowSections(rows: TodayPeopleRow[]): TodayPeopleRowSectionGroup[] {
    return (Object.keys(TODAY_PEOPLE_ROW_SECTION_LABELS) as TodayPeopleRowSection[])
        .map((key) => ({
            key,
            label: TODAY_PEOPLE_ROW_SECTION_LABELS[key],
            rows: rows.filter((row) => rowSection(row) === key),
        }))
        .filter((section) => section.rows.length > 0)
}

export function activePeopleRow(
    pathname: string,
    rows: TodayPeopleRow[],
    recents: TodayPeopleRecent[],
    openRecent: TodayPeopleRecent | null = null
): string | null {
    const path = removeProjectIdIfPresent(pathname)
    // A row keeps one URL for its record, but other pages can link to the record with another one.
    const recent = recents.find((item) => item.href === openRecent?.href || isUnderPath(path, item.href))
    if (recent) {
        return peopleRecentRowKey(recent.href)
    }
    return rows.find((row) => row.paths.some((rowPath) => isUnderPath(path, rowPath)))?.key ?? null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayPeopleLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    aggregationLabel: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun // groupsModel
    groupTypes: Map<GroupTypeIndex, GroupType> // groupsModel
    groupsAccessStatus: GroupsAccessStatus // groupsModel
    location: {
        pathname: string
        search: string
        hash: string
    } // router
    shortcutData: FileSystemEntry[] // sidebarPinsLogic
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    currentRecent: TodayPeopleRecent | null // todayPeopleRecentsLogic
    recentRows: TodayPeopleRecent[] // todayPeopleRecentsLogic
    recents: TodayPeopleRecent[] // todayPeopleRecentsLogic
    accountsGroupTypeIndex: GroupTypeIndex | null
    activeRow: string | null
    collapsedSections: TodayPeopleSection[]
    counts: TodayPeopleRowCounts
    countsLoading: boolean
    groupTabs: GroupTab[]
    isSearching: boolean
    isSectionOpen: (section: TodayPeopleSection) => boolean
    matchingPinnedRows: TodayPeoplePin[]
    matchingRecentRows: TodayPeopleRecent[]
    matchingRows: TodayPeopleRow[]
    pinnedRows: TodayPeoplePin[]
    rowSections: TodayPeopleRowSectionGroup[]
    rows: TodayPeopleRow[]
    searchQuery: string
    topRows: TodayPeopleRow[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayPeopleLogicActions {
    loadCounts: () => any
    loadCountsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCountsSuccess: (
        counts: Partial<Record<'accounts' | 'cohorts' | 'journeys', number>>,
        payload?: any
    ) => {
        counts: Partial<Record<'accounts' | 'cohorts' | 'journeys', number>>
        payload?: any
    }
    setSearchQuery: (searchQuery: string) => {
        searchQuery: string
    }
    toggleSection: (section: TodayPeopleSection) => {
        section: TodayPeopleSection
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayPeopleLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        accountsGroupTypeIndex: (
            currentTeam: TeamPublicType | TeamType | null,
            groupTypes: Map<GroupTypeIndex, GroupType>
        ) => GroupTypeIndex | null
        groupTabs: (
            groupTypes: Map<GroupTypeIndex, GroupType>,
            groupsAccessStatus: GroupsAccessStatus,
            aggregationLabel: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun // groupsModel
        ) => GroupTab[]
        rows: (
            featureFlags: FeatureFlagsSet,
            accountsGroupTypeIndex: GroupTypeIndex | null,
            groupTabs: GroupTab[]
        ) => TodayPeopleRow[]
        activeRow: (
            location: {
                hash: string
                pathname: string
                search: string
            },
            rows: TodayPeopleRow[],
            recents: TodayPeopleRecent[],
            currentRecent: TodayPeopleRecent | null
        ) => string | null
        matchingRows: (rows: TodayPeopleRow[], searchQuery: string) => TodayPeopleRow[]
        topRows: (matchingRows: TodayPeopleRow[]) => TodayPeopleRow[]
        rowSections: (matchingRows: TodayPeopleRow[]) => TodayPeopleRowSectionGroup[]
        pinnedRows: (shortcutData: FileSystemEntry[]) => TodayPeoplePin[]
        matchingPinnedRows: (pinnedRows: TodayPeoplePin[], searchQuery: string) => TodayPeoplePin[]
        matchingRecentRows: (
            recentRows: TodayPeopleRecent[],
            pinnedRows: TodayPeoplePin[],
            searchQuery: string
        ) => TodayPeopleRecent[]
        isSearching: (searchQuery: string) => boolean
        isSectionOpen: (
            collapsedSections: TodayPeopleSection[],
            isSearching: boolean
        ) => (section: TodayPeopleSection) => boolean
    }
}

export type todayPeopleLogicType = MakeLogicType<
    todayPeopleLogicValues,
    todayPeopleLogicActions,
    Record<string, any>,
    todayPeopleLogicMeta
>

export const todayPeopleLogic = kea<todayPeopleLogicType>([
    path(['layout', 'today', 'todayPeopleLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            groupsModel,
            ['groupTypes', 'groupsAccessStatus', 'aggregationLabel'],
            todayPeopleRecentsLogic,
            ['recents', 'recentRows', 'currentRecent'],
            router,
            ['location'],
            teamLogic,
            ['currentTeam'],
            sidebarPinsLogic,
            ['shortcutData'],
        ],
    })),
    actions({
        toggleSection: (section: TodayPeopleSection) => ({ section }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
    }),
    loaders(({ values }) => ({
        counts: [
            {} as TodayPeopleRowCounts,
            {
                // Each count stands alone: one the person cannot read leaves only its own row without a number.
                loadCounts: async (): Promise<TodayPeopleRowCounts> => {
                    const projectId = values.currentTeam?.project_id
                    if (!projectId) {
                        return {}
                    }
                    const id = String(projectId)
                    const { featureFlags, accountsGroupTypeIndex } = values
                    const customerAnalytics = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS]
                    const accountsCount = async (): Promise<number | undefined> => {
                        if (customerAnalytics && featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]) {
                            return (await accountsList(id, { limit: 1 })).count
                        }
                        if (!customerAnalytics || accountsGroupTypeIndex === null) {
                            return undefined
                        }
                        const response = await api.queryHogQL<[number][]>(
                            hogql`SELECT count() FROM groups WHERE index = ${accountsGroupTypeIndex}`,
                            {
                                scene: 'TodayPeopleSidebar',
                                productKey: 'customer_analytics',
                                name: 'today_people_accounts_count',
                            }
                        )
                        return response.results?.[0]?.[0]
                    }
                    const [accounts, cohorts, journeys] = await Promise.allSettled([
                        accountsCount(),
                        cohortsList(id, { limit: 1 }).then((response) => response.count),
                        customerAnalytics && featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]
                            ? customerJourneysList(id, { limit: 1 }).then((response) => response.count)
                            : undefined,
                    ])
                    const value = (result: PromiseSettledResult<number | undefined>): number | undefined =>
                        result.status === 'fulfilled' ? result.value : undefined
                    return { accounts: value(accounts), cohorts: value(cohorts), journeys: value(journeys) }
                },
            },
        ],
    })),
    reducers({
        // pinned: storage key for the persisted sections. Renaming it reopens everyone's sections.
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        collapsedSections: [
            [] as TodayPeopleSection[],
            TODAY_USER_PERSIST_OPTIONS,
            {
                toggleSection: (state, { section }) =>
                    state.includes(section) ? state.filter((id) => id !== section) : [...state, section],
            },
        ],
    }),
    selectors({
        accountsGroupTypeIndex: [
            (s) => [s.currentTeam, s.groupTypes],
            (
                currentTeam: TeamPublicType | TeamType | null,
                groupTypes: Map<GroupTypeIndex, GroupType>
            ): GroupTypeIndex | null =>
                accountGroupTypeIndex(
                    currentTeam && 'customer_analytics_config' in currentTeam
                        ? currentTeam.customer_analytics_config?.account_group_type_index
                        : null,
                    groupTypes
                ),
        ],
        groupTabs: [
            (s) => [s.groupTypes, s.groupsAccessStatus, s.aggregationLabel],
            (
                groupTypes: Map<GroupTypeIndex, GroupType>,
                groupsAccessStatus: GroupsAccessStatus,
                aggregationLabel: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun
            ): GroupTab[] => groupTabsFor(groupTypes, groupsAccessStatus, aggregationLabel),
        ],
        rows: [
            (s) => [s.featureFlags, s.accountsGroupTypeIndex, s.groupTabs],
            (
                featureFlags: FeatureFlagsSet,
                groupTypeIndex: GroupTypeIndex | null,
                groupTabs: GroupTab[]
            ): TodayPeopleRow[] => peopleSidebarRows(featureFlags, groupTypeIndex, groupTabs),
        ],
        activeRow: [
            (s) => [s.location, s.rows, s.recents, s.currentRecent],
            (
                location: { pathname: string },
                rows: TodayPeopleRow[],
                recents: TodayPeopleRecent[],
                currentRecent: TodayPeopleRecent | null
            ): string | null => activePeopleRow(location.pathname, rows, recents, currentRecent),
        ],
        matchingRows: [
            (s) => [s.rows, s.searchQuery],
            (rows: TodayPeopleRow[], searchQuery: string): TodayPeopleRow[] =>
                rows.filter((row) => matchesPaneQuery(row.label, searchQuery)),
        ],
        topRows: [
            (s) => [s.matchingRows],
            (rows: TodayPeopleRow[]): TodayPeopleRow[] => rows.filter((row) => rowSection(row) === null),
        ],
        rowSections: [
            (s) => [s.matchingRows],
            (rows: TodayPeopleRow[]): TodayPeopleRowSectionGroup[] => peopleRowSections(rows),
        ],
        pinnedRows: [
            (s) => [s.shortcutData],
            (shortcutData: FileSystemEntry[]): TodayPeoplePin[] => peoplePinsFromShortcuts(shortcutData),
        ],
        matchingPinnedRows: [
            (s) => [s.pinnedRows, s.searchQuery],
            (pinnedRows: TodayPeoplePin[], searchQuery: string): TodayPeoplePin[] =>
                pinnedRows.filter((pin) => matchesPaneQuery(pin.name, searchQuery)),
        ],
        // A pinned record shows once, under Pinned, so its row value stays unique on the keyboard path.
        matchingRecentRows: [
            (s) => [s.recentRows, s.pinnedRows, s.searchQuery],
            (
                recentRows: TodayPeopleRecent[],
                pinnedRows: TodayPeoplePin[],
                searchQuery: string
            ): TodayPeopleRecent[] => {
                const pinnedHrefs = new Set(pinnedRows.map((pin) => pin.href))
                return recentRows.filter(
                    (recent) => !pinnedHrefs.has(recent.href) && matchesPaneQuery(recent.name, searchQuery)
                )
            },
        ],
        isSearching: [(s) => [s.searchQuery], (searchQuery: string): boolean => searchQuery.trim() !== ''],
        /** A search opens every section, so no match hides in a collapsed one. */
        isSectionOpen: [
            (s) => [s.collapsedSections, s.isSearching],
            (collapsedSections: TodayPeopleSection[], isSearching: boolean) =>
                (section: TodayPeopleSection): boolean =>
                    isSearching || !collapsedSections.includes(section),
        ],
    }),
    listeners(({ values }) => ({
        toggleSection: ({ section }) => {
            // pinned: analytics event name and properties. Renaming them breaks dashboards.
            posthog.capture('people section toggled', {
                section,
                open: !values.collapsedSections.includes(section),
            })
        },
    })),
    subscriptions(({ actions }) => ({
        // Runs on mount, and again once group types load, because the Accounts count can depend on them.
        accountsGroupTypeIndex: () => actions.loadCounts(),
    })),
])
