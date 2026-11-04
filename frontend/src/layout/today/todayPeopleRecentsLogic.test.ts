import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { initKeaTests } from '~/test/init'
import { Breadcrumb } from '~/types'

import {
    TODAY_PEOPLE_RECENTS_LIMIT,
    TodayPeopleRecent,
    addPeopleRecent,
    peopleRecentForPage,
    todayPeopleRecentsLogic,
} from './todayPeopleRecentsLogic'

// The real logic reads the crumbs off the mounted scene. This one lets a test set them.
jest.mock('~/layout/navigation/Breadcrumbs/breadcrumbsLogic', () => {
    const { actions, kea, path, reducers } = jest.requireActual('kea')
    return {
        breadcrumbsLogic: kea([
            path(['test', 'breadcrumbsLogic']),
            actions({ setCrumbs: (crumbs: unknown[]) => ({ crumbs }) }),
            reducers({
                sceneBreadcrumbs: [[], { setCrumbs: (_: unknown, { crumbs }: { crumbs: unknown[] }) => crumbs }],
            }),
        ]),
    }
})

const crumb = (key: Breadcrumb['key'], name: string): Breadcrumb => ({ key, name }) as Breadcrumb
const recent = (href: string, name: string = href): TodayPeopleRecent => ({ type: 'cohort', name, href })

describe('todayPeopleRecentsLogic', () => {
    test.each([
        ['/project/1/person/ada%40example.com', [Scene.Person, 'id'], 'person', '/person/ada%40example.com'],
        ['/project/1/persons/0190-uuid', [Scene.Person, 'id'], 'person', '/persons/0190-uuid'],
        ['/project/1/groups/0/acme', [Scene.Group, '0-acme'], 'group', '/groups/0/acme'],
        ['/project/1/groups/0/acme/events', [Scene.Group, '0-acme'], 'group', '/groups/0/acme'],
        ['/project/1/cohorts/5', [Scene.Cohort, 5], 'cohort', '/cohorts/5'],
        [
            '/project/1/customer_analytics/accounts/7/notes',
            Scene.CustomerAnalyticsAccount,
            'account',
            '/customer_analytics/accounts/7',
        ],
        [
            '/project/1/customer_analytics/accounts/by-external-id/ext-1',
            Scene.CustomerAnalyticsAccount,
            'account',
            '/customer_analytics/accounts/by-external-id/ext-1',
        ],
        ['/project/1/support/tickets/12', ['SupportTicketDetail', '12'], 'ticket', '/support/tickets/12'],
    ])('tracks %s', (pathname, key, type, href) => {
        expect(peopleRecentForPage(pathname, [crumb('list', 'List'), crumb(key as Breadcrumb['key'], 'Name')])).toEqual(
            { type, name: 'Name', href }
        )
    })

    test.each([
        ['a list page', '/project/1/persons', [Scene.Persons, 'x']],
        ['a new group', '/project/1/groups/0/new', [Scene.Group, 'x']],
        ['a new cohort', '/project/1/cohorts/new', [Scene.Cohort, 'x']],
        ['a new ticket', '/project/1/support/tickets/new', ['SupportTicketDetail', 'new']],
        ['an untracked page', '/project/1/insights/abc', [Scene.Insight, 'x']],
        ['a person whose crumb has not loaded', '/project/1/person/ada', Scene.Persons],
        ['the crumb of the page before', '/project/1/cohorts/5', [Scene.Person, 'x']],
    ])('skips %s', (_, pathname, key) => {
        expect(peopleRecentForPage(pathname, [crumb(key as Breadcrumb['key'], 'Name')])).toBeNull()
    })

    it('puts a visit first, renames it in place, and keeps the list at the limit', () => {
        const a = recent('/a')
        const b = recent('/b')
        expect(addPeopleRecent([a, b], b).map((item) => item.href)).toEqual(['/b', '/a'])
        expect(addPeopleRecent([a, b], { ...a, name: 'Renamed' })).toEqual([{ ...a, name: 'Renamed' }, b])

        const unchanged = [a, b]
        expect(addPeopleRecent(unchanged, a)).toBe(unchanged)

        const full = Array.from({ length: TODAY_PEOPLE_RECENTS_LIMIT }, (_, index) => recent(`/${index}`))
        const added = addPeopleRecent(full, recent('/new'))
        expect(added).toHaveLength(TODAY_PEOPLE_RECENTS_LIMIT)
        expect(added[0].href).toBe('/new')
    })

    test.each([
        ['on', true, ['Churned']],
        ['off', false, []],
    ])('with today-rail-nav %s, opening a cohort adds %o once its crumb loads', (_, enabled, names) => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: enabled,
        })
        breadcrumbsLogic.mount()
        const logic = todayPeopleRecentsLogic()
        logic.mount()

        router.actions.push('/project/1/cohorts/5')
        ;(breadcrumbsLogic.actions as any).setCrumbs([crumb(Scene.Cohorts, 'Cohorts')])
        expect(logic.values.recents).toEqual([])

        ;(breadcrumbsLogic.actions as any).setCrumbs([crumb([Scene.Cohort, 5], 'Churned')])
        expect(logic.values.recents.map((item) => item.name)).toEqual(names)
    })

    it('stores a recent, newest first', () => {
        initKeaTests()
        const logic = todayPeopleRecentsLogic()
        logic.mount()

        logic.actions.addRecent(recent('/cohorts/1'))
        logic.actions.addRecent(recent('/cohorts/2'))

        expect(logic.values.recents.map((item) => item.href)).toEqual(['/cohorts/2', '/cohorts/1'])
    })
})
