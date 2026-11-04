import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamIdOrNone, getCurrentUserIdOrNone } from 'lib/utils/getAppContext'
import { hogql } from 'lib/utils/hogql'
import { isUnderPath, removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { ActivitySceneTab, activitySceneTabsLogic } from 'scenes/activity/activitySceneTabsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { GroupType, GroupTypeIndex, TeamPublicType, TeamType } from '~/types'

import { cohortsList } from 'products/cohorts/frontend/generated/api'
import { accountsList, customerJourneysList } from 'products/customer_analytics/frontend/generated/api'

import { TodayPeopleRecent, todayPeopleRecentsLogic } from './todayPeopleRecentsLogic'

// pinned: persisted section ids and the `section` property of `people section toggled`.
export type TodayPeopleSection = 'recents'

/** The rows always on show. The others wait behind See more. */
const PRIMARY_ROW_KEYS: TodayPeopleRowKey[] = ['overview', 'persons', 'accounts', 'cohorts', 'journeys']

export type TodayPeopleRowCounts = Partial<Record<'accounts' | 'cohorts' | 'journeys', number>>

// pinned: the row ids. Each one is part of the row's `people-sidebar-<row>` data-attr.
export type TodayPeopleRowKey =
    | 'overview'
    | 'feed'
    | 'tasks'
    | 'persons'
    | 'accounts'
    | 'cohorts'
    | 'journeys'
    | 'notes'
    | 'announcements'
    | 'feature_requests'
    | 'support'
    | `groups-${number}`

export interface TodayPeopleRow {
    key: TodayPeopleRowKey
    label: string
    href: string
    /** The paths that mark the row active. */
    paths: string[]
}

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
    groupTabs: ActivitySceneTab[] = []
): TodayPeopleRow[] {
    const customerAnalytics = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS]
    const csp = customerAnalytics && !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]
    const journeys = customerAnalytics && !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]
    const featureRequests = customerAnalytics && !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS]
    const tasks = customerAnalytics && !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]
    const row = (key: TodayPeopleRowKey, label: string, href: string, paths: string[] = [href]): TodayPeopleRow => ({
        key,
        label,
        href,
        paths,
    })
    const rows: (TodayPeopleRow | null)[] = [
        customerAnalytics ? row('overview', 'Overview', urls.customerAnalyticsDashboard()) : null,
        csp ? row('feed', 'Feed', urls.customerAnalyticsFeed()) : null,
        tasks ? row('tasks', 'Tasks', urls.customerAnalyticsTasks()) : null,
        row('persons', 'Persons', urls.persons(), [urls.persons(), '/person']),
        csp ? row('accounts', 'Accounts', urls.customerAnalyticsAccounts()) : null,
        ...groupTabs.map((tab) => {
            const isAccounts = !csp && tab.key === `groups-${groupTypeIndex}`
            // Accounts names one row only: the tab with customer-analytics-csp, else the account group type.
            const label = isAccounts ? 'Accounts' : tab.label === 'Accounts' ? 'Groups' : tab.label
            return row(isAccounts ? 'accounts' : (tab.key as TodayPeopleRowKey), label, tab.url)
        }),
        row('cohorts', 'Cohorts', urls.cohorts()),
        journeys ? row('journeys', 'Journeys', urls.customerAnalyticsJourneys()) : null,
        csp ? row('notes', 'Notes', urls.customerAnalyticsNotes()) : null,
        csp ? row('announcements', 'Announcements', urls.customerAnalyticsAnnouncements()) : null,
        featureRequests ? row('feature_requests', 'Feature requests', urls.customerAnalyticsFeatureRequests()) : null,
        row('support', 'Support', urls.supportTickets(), [urls.supportDashboard()]),
    ]
    return rows.filter((row): row is TodayPeopleRow => row !== null)
}

/** The rows behind See more to show: all of them when open, else only the one for the open page. */
export function visibleMoreRows(rows: TodayPeopleRow[], moreOpen: boolean, activeRow: string | null): TodayPeopleRow[] {
    return rows.filter((row) => !PRIMARY_ROW_KEYS.includes(row.key) && (moreOpen || row.key === activeRow))
}

export function activePeopleRow(pathname: string, rows: TodayPeopleRow[], recents: TodayPeopleRecent[]): string | null {
    const path = removeProjectIdIfPresent(pathname)
    const recent = recents.find((item) => isUnderPath(path, item.href))
    if (recent) {
        return `recent:${recent.href}`
    }
    return rows.find((row) => row.paths.some((rowPath) => isUnderPath(path, rowPath)))?.key ?? null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayPeopleLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    groupTypes: Map<GroupTypeIndex, GroupType> // groupsModel
    groupTabs: ActivitySceneTab[] // activitySceneTabsLogic
    recents: TodayPeopleRecent[] // todayPeopleRecentsLogic
    location: {
        pathname: string
        search: string
        hash: string
    } // router
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    accountsGroupTypeIndex: GroupTypeIndex | null
    activeRow: string | null
    collapsedSections: TodayPeopleSection[]
    counts: TodayPeopleRowCounts
    countsLoading: boolean
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
        counts: TodayPeopleRowCounts,
        payload?: any
    ) => {
        counts: TodayPeopleRowCounts
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
        rows: (
            featureFlags: FeatureFlagsSet,
            accountsGroupTypeIndex: GroupTypeIndex | null,
            groupTabs: ActivitySceneTab[]
        ) => TodayPeopleRow[]
        activeRow: (
            location: {
                hash: string
                pathname: string
                search: string
            },
            rows: TodayPeopleRow[],
            recents: TodayPeopleRecent[]
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
            ['groupTypes'],
            activitySceneTabsLogic,
            ['groupTabs'],
            todayPeopleRecentsLogic,
            ['recents'],
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
        rows: [
            (s) => [s.featureFlags, s.accountsGroupTypeIndex, s.groupTabs],
            (
                featureFlags: FeatureFlagsSet,
                groupTypeIndex: GroupTypeIndex | null,
                groupTabs: ActivitySceneTab[]
            ): TodayPeopleRow[] => peopleSidebarRows(featureFlags, groupTypeIndex, groupTabs),
        ],
        activeRow: [
            (s) => [s.location, s.rows, s.recents],
            (location: { pathname: string }, rows: TodayPeopleRow[], recents: TodayPeopleRecent[]): string | null =>
                activePeopleRow(location.pathname, rows, recents),
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
