import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'
import { useMocks } from '~/mocks/jest'
import { GroupTab } from '~/models/groupTabs'
import { initKeaTests } from '~/test/init'
import { GroupType, GroupTypeIndex } from '~/types'

import {
    accountGroupTypeIndex,
    activePeopleRow,
    peopleRowSections,
    peopleSidebarRows,
    todayPeopleLogic,
} from './todayPeopleLogic'
import { todayPeopleRecentsLogic } from './todayPeopleRecentsLogic'

const groupTypes = (...indexes: number[]): Map<GroupTypeIndex, GroupType> =>
    new Map(
        indexes.map((index) => [
            index as GroupTypeIndex,
            { group_type: `type-${index}`, group_type_index: index as GroupTypeIndex },
        ])
    )

const CUSTOMER_ANALYTICS = { [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true }
const JOURNEYS = { ...CUSTOMER_ANALYTICS, [FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]: true }
const EVERY_TAB = {
    ...JOURNEYS,
    [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true,
    [FEATURE_FLAGS.CUSTOMER_ANALYTICS_FEATURE_REQUESTS]: true,
    [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]: true,
}

const groupTabs = (...tabs: [number, string][]): GroupTab[] =>
    tabs.map(([index, label]) => ({
        key: `groups-${index}`,
        label,
        url: urls.groups(index),
        iconType: 'group',
        dataAttr: 'tab',
    }))
const ONE_TYPE = groupTabs([0, 'Organizations'])

describe('todayPeopleLogic', () => {
    test.each([
        [
            'journeys on',
            JOURNEYS,
            0,
            ['overview', 'persons', 'accounts', 'cohorts', 'journeys', 'configure', 'support'],
        ],
        [
            'every tab on',
            EVERY_TAB,
            0,
            [
                'overview',
                'feed',
                'tasks',
                'persons',
                'accounts',
                'cohorts',
                'journeys',
                'notes',
                'announcements',
                'feature_requests',
                'configure',
                'support',
            ],
        ],
        ['journeys off', CUSTOMER_ANALYTICS, 0, ['overview', 'persons', 'accounts', 'cohorts', 'configure', 'support']],
        [
            'customer analytics off, tab flags on',
            { ...EVERY_TAB, [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: false },
            0,
            ['persons', 'groups-0', 'cohorts', 'support'],
        ],
        ['no group types', JOURNEYS, null, ['overview', 'persons', 'cohorts', 'journeys', 'configure', 'support']],
    ])('with %s, the pane shows %o', (_, flags, groupTypeIndex, keys) => {
        expect(
            peopleSidebarRows(
                flags,
                groupTypeIndex as GroupTypeIndex | null,
                groupTypeIndex === null ? [] : ONE_TYPE
            ).map((row) => row.key)
        ).toEqual(keys)
    })

    test.each([
        ['off, the group list', {}, urls.groups(0)],
        ['on, the Accounts tab', { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true }, urls.customerAnalyticsAccounts()],
    ])('with customer-analytics-csp %s opens from Accounts', (_, flags, href) => {
        const accounts = peopleSidebarRows({ ...CUSTOMER_ANALYTICS, ...flags }, 0, ONE_TYPE).find(
            (row) => row.key === 'accounts'
        )
        expect(accounts?.href).toBe(href)
    })

    it('lists every group type by its own name, and the account group type once', () => {
        const tabs = groupTabs([0, 'Accounts'], [1, 'Projects'])
        const rowsFor = (flags: Record<string, boolean>, index: GroupTypeIndex): [string, string, string][] =>
            peopleSidebarRows(flags, index, tabs)
                .filter((row) => row.key === 'accounts' || row.key.startsWith('groups-'))
                .map((row) => [row.key, row.label, row.href])

        expect(rowsFor(CUSTOMER_ANALYTICS, 1)).toEqual([
            ['accounts', 'Accounts', urls.groups(1)],
            ['groups-0', 'Accounts', urls.groups(0)],
        ])
        expect(rowsFor({ ...CUSTOMER_ANALYTICS, [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true }, 0)).toEqual([
            ['accounts', 'Accounts', urls.customerAnalyticsAccounts()],
            ['groups-1', 'Projects', urls.groups(1)],
        ])
    })

    it('puts the core rows and Support on top, and the rest in Groups and Customer analytics', () => {
        const rows = peopleSidebarRows(EVERY_TAB, 1, groupTabs([0, 'Organizations'], [1, 'Projects']))

        expect(
            rows.filter((row) => !peopleRowSections(rows).some((s) => s.rows.includes(row))).map((row) => row.key)
        ).toEqual(['overview', 'persons', 'accounts', 'cohorts', 'support'])
        expect(peopleRowSections(rows).map((section) => [section.label, section.rows.map((row) => row.key)])).toEqual([
            ['Groups', ['groups-0']],
            [
                'Customer analytics',
                ['feed', 'tasks', 'journeys', 'notes', 'announcements', 'feature_requests', 'configure'],
            ],
        ])
    })

    it('leaves out a section with no rows', () => {
        const rows = peopleSidebarRows(JOURNEYS, 0, ONE_TYPE)
        expect(peopleRowSections(rows).map((section) => section.key)).toEqual(['customer-analytics'])
    })

    test.each([
        ['the configured account type', 1, groupTypes(0, 1), 1],
        ['the first type when none is configured', null, groupTypes(2, 0), 0],
        ['the first type when the configured one was deleted', 3, groupTypes(1, 2), 1],
        ['nothing without group types', 0, groupTypes(), null],
    ])('the Accounts row opens %s', (_, configured, types, index) => {
        expect(accountGroupTypeIndex(configured, types)).toBe(index)
    })

    it('marks the open record active when its page has another URL than its row', () => {
        const row = { type: 'person' as const, name: 'Ada', href: urls.personByUUID('uuid-1') }
        expect(activePeopleRow('/project/1/person/ada', peopleSidebarRows(JOURNEYS, 0, ONE_TYPE), [row], row)).toBe(
            `recent:${row.href}`
        )
    })

    test.each([
        ['/project/1/person/ada%40example.com', JOURNEYS, 'persons'],
        ['/project/1/groups/0/acme', JOURNEYS, 'accounts'],
        ['/project/1/groups/0/acme', EVERY_TAB, 'accounts'],
        ['/project/1/customer_analytics/accounts/7', EVERY_TAB, 'accounts'],
        ['/project/1/customer_analytics/feature-requests/3', EVERY_TAB, 'feature_requests'],
        ['/project/1/support/tickets', JOURNEYS, 'support'],
        ['/project/1/support/tickets/12', JOURNEYS, 'support'],
        ['/project/1/cohorts', JOURNEYS, 'cohorts'],
        ['/project/1/cohorts/2', JOURNEYS, `recent:${urls.cohort('2')}`],
        ['/project/1/cohorts/9', JOURNEYS, 'cohorts'],
        ['/project/1/customer_analytics/journeys/new', JOURNEYS, 'journeys'],
        ['/project/1/insights/abc', JOURNEYS, null],
    ])('on %s with flags %o the %s row is active', (pathname, flags, active) => {
        const recents = [{ type: 'cohort' as const, name: 'Churned', href: urls.cohort('2') }]
        expect(activePeopleRow(pathname, peopleSidebarRows(flags, 0, ONE_TYPE), recents)).toBe(active)
    })

    it('keeps the other counts when one count request fails', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/accounts/': { count: 4, results: [] },
                '/api/projects/:team_id/cohorts/': () => [500, { detail: 'nope' }],
                '/api/projects/:team_id/customer_journeys/': { count: 2, results: [] },
            },
        })
        initKeaTests()
        const flags = { ...JOURNEYS, [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true }
        featureFlagLogic.actions.setFeatureFlags(Object.keys(flags), flags)
        const logic = todayPeopleLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadCountsSuccess'])
        expect(logic.values.counts).toEqual({ accounts: 4, cohorts: undefined, journeys: 2 })
    })

    it('filters every list by the search and opens collapsed sections while searching', () => {
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags(Object.keys(EVERY_TAB), EVERY_TAB)
        const logic = todayPeopleLogic()
        logic.mount()
        logic.actions.toggleSection('customer-analytics')
        expect(logic.values.isSectionOpen('customer-analytics')).toBe(false)

        logic.actions.setSearchQuery('ANNOUNCE')

        expect(logic.values.topRows).toEqual([])
        expect(logic.values.rowSections.map((section) => section.rows.map((row) => row.key))).toEqual([
            ['announcements'],
        ])
        expect(logic.values.isSectionOpen('customer-analytics')).toBe(true)

        logic.actions.setSearchQuery('')
        expect(logic.values.isSectionOpen('customer-analytics')).toBe(false)
    })

    it('lists a cohort starred in the classic navigation under Pinned, not Recents, and its title pin removes the star', async () => {
        const requests: string[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/file_system_shortcut/': {
                    results: [
                        { id: 'sc-dashboard', type: 'dashboard', path: 'KPIs', ref: '7', href: '/dashboard/7' },
                        {
                            id: 'sc-cohort',
                            type: 'cohort',
                            path: 'Unfiled/Power users',
                            ref: '12',
                            href: '/cohorts/12',
                        },
                    ],
                },
            },
            delete: {
                '/api/projects/:team_id/file_system_shortcut/:id/': ({ params }) => {
                    requests.push(`delete ${params.id}`)
                    return [204, null]
                },
            },
        })
        initKeaTests()
        const logic = todayPeopleLogic()
        logic.mount()
        todayPeopleRecentsLogic.actions.addRecent({ type: 'cohort', name: 'Power users', href: '/cohorts/12' })
        todayPeopleRecentsLogic.actions.addRecent({ type: 'person', name: 'Ada', href: '/persons/ada' })
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])

        expect(logic.values.pinnedRows).toEqual([
            { key: 'cohort:/cohorts/12', type: 'cohort', name: 'Power users', href: '/cohorts/12' },
        ])
        expect(logic.values.matchingRecentRows.map((recent) => recent.name)).toEqual(['Ada'])

        await expectLogic(sidebarPinsLogic, () =>
            sidebarPinsLogic.actions.togglePinned({ type: 'cohort', name: 'Power users', href: '/cohorts/12' })
        ).toDispatchActions(projectTreeDataLogic, ['deleteShortcutSuccess'])
        expect(requests).toEqual(['delete sc-cohort'])
        expect(logic.values.pinnedRows).toEqual([])
    })
})
