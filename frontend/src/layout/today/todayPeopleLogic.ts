import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamIdOrNone, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'
import { hogql } from 'lib/utils/hogql'
import { isUnderPath, removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Noun, groupsModel } from '~/models/groupsModel'
import { GroupTab, groupTabs as groupTabsFor } from '~/models/groupTabs'
import { GroupType, GroupTypeIndex, TeamPublicType, TeamType } from '~/types'

import { cohortsList } from 'products/cohorts/frontend/generated/api'
import { accountsList, customerJourneysList } from 'products/customer_analytics/frontend/generated/api'

import { TODAY_PEOPLE_ROW_LABELS, TodayPeopleRecent, TodayPeopleStaticRowKey } from './todayPeopleModel'
import { todayPeopleRecentsLogic } from './todayPeopleRecentsLogic'

// pinned: persisted section ids and the `section` property of `people section toggled`.
export type TodayPeopleSection = 'recents'

/** The rows always on show. The others wait behind See more. */
const PRIMARY_ROW_KEYS: TodayPeopleRowKey[] = ['overview', 'persons', 'accounts', 'cohorts', 'journeys']

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

// Collapsed sections belong to one person in one project. Without both ids nothing persists.
const TEAM_ID = getCurrentTeamIdOrNone()
const USER_ID = getCurrentUserIdOrNone()
const SECTIONS_PERSIST_OPTIONS =
    TEAM_ID && USER_ID ? { persist: true, prefix: `${TEAM_ID}__${USER_ID}__` } : { persist: false }

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

/**
 * The rows at the top of the People pane. They carry the Customer analytics tabs, which this shell hides, under the
 * same flags as the tabs, and every group type, so the tab bars on those pages can go.
 */
export function peopleSidebarRows(
    featureFlags: FeatureFlagsSet,
    groupTypeIndex: GroupTypeIndex | null,
    groupTabs: GroupTab[] = []
): TodayPeopleRow[] {
    const customerAnalytics = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS]
    const csp = customerAnalytics && !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]
    const journeys = customerAnalytics && !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]
    const featureRequests = customerAnalytics && !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS]
    const tasks = customerAnalytics && !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]
    const row = (
        key: TodayPeopleStaticRowKey,
        href: string,
        paths: string[] = [href],
        label: string = TODAY_PEOPLE_ROW_LABELS[key]
    ): TodayPeopleRow => ({ kind: 'static', key, label, href, paths })
    const rows: (TodayPeopleRow | null)[] = [
        customerAnalytics ? row('overview', urls.customerAnalyticsDashboard()) : null,
        csp ? row('feed', urls.customerAnalyticsFeed()) : null,
        tasks ? row('tasks', urls.customerAnalyticsTasks()) : null,
        row('persons', urls.persons(), [urls.persons(), '/person']),
        csp ? row('accounts', urls.customerAnalyticsAccounts()) : null,
        ...groupTabs.map((tab): TodayPeopleRow => {
            // Accounts names one row only: the tab with customer-analytics-csp, else the account group type.
            if (!csp && tab.key === `groups-${groupTypeIndex}`) {
                return row('accounts', tab.url)
            }
            const label = tab.label === TODAY_PEOPLE_ROW_LABELS.accounts ? 'Groups' : tab.label
            return { kind: 'group', key: tab.key, label, href: tab.url, paths: [tab.url] }
        }),
        row('cohorts', urls.cohorts()),
        journeys ? row('journeys', urls.customerAnalyticsJourneys()) : null,
        csp ? row('notes', urls.customerAnalyticsNotes()) : null,
        csp ? row('announcements', urls.customerAnalyticsAnnouncements()) : null,
        featureRequests ? row('feature_requests', urls.customerAnalyticsFeatureRequests()) : null,
        row('support', urls.supportTickets(), [urls.supportDashboard()]),
    ]
    return rows.filter((row): row is TodayPeopleRow => row !== null)
}

/** The rows behind See more to show: all of them when open, else only the one for the open page. */
export function visibleMoreRows(rows: TodayPeopleRow[], moreOpen: boolean, activeRow: string | null): TodayPeopleRow[] {
    return rows.filter((row) => !PRIMARY_ROW_KEYS.includes(row.key) && (moreOpen || row.key === activeRow))
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
        return `recent:${recent.href}`
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
    hasMoreRows: boolean
    moreOpen: boolean
    moreRows: TodayPeopleRow[]
    primaryRows: TodayPeopleRow[]
    rows: TodayPeopleRow[]
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
    toggleMore: () => {
        value: true
    }
    toggleSection: (section: TodayPeopleSection) => {
        section: 'recents'
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
            aggregationLabel: (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun
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
        primaryRows: (rows: TodayPeopleRow[]) => TodayPeopleRow[]
        moreRows: (rows: TodayPeopleRow[], moreOpen: boolean, activeRow: string | null) => TodayPeopleRow[]
        hasMoreRows: (rows: TodayPeopleRow[]) => boolean
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
        ],
    })),
    actions({
        toggleSection: (section: TodayPeopleSection) => ({ section }),
        toggleMore: true,
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
                        if (accountsGroupTypeIndex === null) {
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
        collapsedSections: [
            [] as TodayPeopleSection[],
            SECTIONS_PERSIST_OPTIONS,
            {
                toggleSection: (state, { section }) =>
                    state.includes(section) ? state.filter((id) => id !== section) : [...state, section],
            },
        ],
        moreOpen: [
            false,
            SECTIONS_PERSIST_OPTIONS,
            {
                toggleMore: (state) => !state,
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
        primaryRows: [
            (s) => [s.rows],
            (rows: TodayPeopleRow[]): TodayPeopleRow[] => rows.filter((row) => PRIMARY_ROW_KEYS.includes(row.key)),
        ],
        moreRows: [
            (s) => [s.rows, s.moreOpen, s.activeRow],
            (rows: TodayPeopleRow[], moreOpen: boolean, activeRow: string | null): TodayPeopleRow[] =>
                visibleMoreRows(rows, moreOpen, activeRow),
        ],
        hasMoreRows: [
            (s) => [s.rows],
            (rows: TodayPeopleRow[]): boolean => rows.some((row) => !PRIMARY_ROW_KEYS.includes(row.key)),
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
        // Group types load after this logic mounts, and the Accounts count can depend on them.
        accountsGroupTypeIndex: () => actions.loadCounts(),
    })),
    afterMount(({ actions }) => {
        actions.loadCounts()
    }),
])
