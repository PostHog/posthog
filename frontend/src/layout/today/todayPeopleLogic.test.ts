import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { GroupType, GroupTypeIndex } from '~/types'

import { accountGroupTypeIndex, activePeopleRow, peopleSidebarRows, todayPeopleLogic } from './todayPeopleLogic'

const groupTypes = (...indexes: number[]): Map<GroupTypeIndex, GroupType> =>
    new Map(
        indexes.map((index) => [
            index as GroupTypeIndex,
            { group_type: `type-${index}`, group_type_index: index as GroupTypeIndex },
        ])
    )

const CUSTOMER_ANALYTICS = { [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true }
const JOURNEYS = { ...CUSTOMER_ANALYTICS, [FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]: true }
const ALL_ROWS = ['overview', 'persons', 'accounts', 'cohorts', 'journeys']

describe('todayPeopleLogic', () => {
    test.each([
        ['every flag on', JOURNEYS, 0, ALL_ROWS],
        ['customer-analytics-csp on too', { ...JOURNEYS, [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CSP]: true }, 0, ALL_ROWS],
        ['journeys off', CUSTOMER_ANALYTICS, 0, ['overview', 'persons', 'accounts', 'cohorts']],
        [
            'customer analytics off',
            { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_JOURNEYS]: true },
            0,
            ['persons', 'accounts', 'cohorts'],
        ],
        ['no group types', JOURNEYS, null, ['overview', 'persons', 'cohorts', 'journeys']],
    ])('with %s, the pane shows %o', (_, flags, groupTypeIndex, keys) => {
        expect(peopleSidebarRows(flags, groupTypeIndex as GroupTypeIndex | null).map((row) => row.key)).toEqual(keys)
    })

    test.each([
        ['the configured account type', 1, groupTypes(0, 1), 1],
        ['the first type when none is configured', null, groupTypes(2, 0), 0],
        ['the first type when the configured one was deleted', 3, groupTypes(1, 2), 1],
        ['nothing without group types', 0, groupTypes(), null],
    ])('the Accounts row opens %s', (_, configured, types, index) => {
        expect(accountGroupTypeIndex(configured, types)).toBe(index)
    })

    test.each([
        ['/project/1/person/ada%40example.com', 'persons'],
        ['/project/1/groups/0/acme', 'accounts'],
        ['/project/1/cohorts', 'cohorts'],
        ['/project/1/cohorts/2', 'recent:2'],
        ['/project/1/cohorts/9', 'cohorts'],
        ['/project/1/customer_analytics/journeys/new', 'journeys'],
        ['/project/1/insights/abc', null],
    ])('on %s the %s row is active', (pathname, active) => {
        const recents = [{ id: '2', name: 'Churned', href: urls.cohort('2') }]
        expect(activePeopleRow(pathname, peopleSidebarRows(JOURNEYS, 0), recents)).toBe(active)
    })

    it('lists recently viewed cohorts only, up to the limit', () => {
        useMocks({ get: { '/api/projects/:team_id/groups_types/': [] } })
        initKeaTests()
        recentItemsModel.mount()
        const logic = todayPeopleLogic()
        logic.mount()
        const row = (type: string, ref: string, name: string): FileSystemEntry =>
            ({ id: `fs-${ref}`, type, ref, path: `Unfiled/${name}`, meta: {} }) as FileSystemEntry

        recentItemsModel.actions.loadRecentsSuccess([
            row('cohort', '1', 'Paying users'),
            row('insight', 'i1', 'Signups'),
            row('cohort', '2', 'Churned'),
            row('cohort', '3', 'Trial'),
            row('cohort', '4', 'Beta'),
        ])
        expect(logic.values.recentCohorts).toEqual([
            { id: '1', name: 'Paying users', href: urls.cohort('1') },
            { id: '2', name: 'Churned', href: urls.cohort('2') },
            { id: '3', name: 'Trial', href: urls.cohort('3') },
        ])
    })
})
