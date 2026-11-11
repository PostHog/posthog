import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { resetAnalyticsFeedSnapshot } from './analyticsFeedLogic'
import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsItem } from './analyticsUtils'

jest.mock('lib/utils/getAppContext', () => ({
    ...jest.requireActual('lib/utils/getAppContext'),
    getCurrentTeamIdOrNone: () => 997,
    getCurrentUserIdOrNone: () => 'u-ada',
}))

const ADA = { id: 1, uuid: 'u-ada', first_name: 'Ada', last_name: '', email: 'ada@example.com' }
const entry = (type: string, ref: string, path: string): Record<string, unknown> => ({
    id: `fs-${ref}`,
    type,
    ref,
    path,
    href: `/x/${ref}`,
    created_at: '2026-09-01T00:00:00Z',
    last_viewed_at: null,
    meta: { created_by: ADA.id },
})

describe('analyticsListLogic', () => {
    let capture: jest.SpyInstance
    let lastViewedAt: string | null
    let failSave: boolean

    beforeEach(() => {
        localStorage.clear()
        lastViewedAt = null
        failSave = false
        resetAnalyticsFeedSnapshot()
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/file_system_shortcut/': { results: [] },
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    if (params.get('parent')) {
                        return { results: [entry('insight/trends', 'i2', 'Growth/I2')], users: [ADA], next: null }
                    }
                    const type = params.get('type') ?? params.get('type__startswith') ?? ''
                    const results =
                        type === 'insight'
                            ? [
                                  entry('insight/trends', 'i1', 'Growth/I1'),
                                  entry('insight/trends', 'i3', 'Unfiled/Insights/I3'),
                              ]
                            : type === 'notebook'
                              ? [entry('notebook', 'n1', 'Users/Ada/N1')]
                              : []
                    return {
                        results: results.map((item) => ({ ...item, last_viewed_at: lastViewedAt })),
                        users: [ADA],
                        next: null,
                    }
                },
            },
            patch: {
                '/api/users/@me/': async ({ request }) =>
                    failSave
                        ? [500, { detail: 'Save failed' }]
                        : { ...userLogic.values.user, ...((await request.json()) as Record<string, unknown>) },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: true,
        })
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    afterEach(() => {
        capture.mockRestore()
    })

    it('lists every row, in and out of collections, including home folder rows', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsList())
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.items.map((item) => [item.id, item.spaceName]).sort()).toEqual([
            ['i1', 'Growth'],
            ['i3', null],
            ['n1', null],
        ])
    })

    it('lets a sort chosen in the menu replace a header click', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        await expectLogic(logic, () => router.actions.push(urls.analyticsList())).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.setFilters({ orderBy: 'created_at' })).toFinishAllListeners()
        expect(logic.values.feedQuery.orderBy).toBe('created_at')

        await expectLogic(logic, () => logic.actions.setDefaultSort('-last_viewed_at')).toFinishAllListeners()

        expect(logic.values.filters.orderBy).toBeUndefined()
        expect(logic.values.feedQuery.orderBy).toBe('-last_viewed_at')
        expect(router.values.searchParams.orderBy).toBeUndefined()
    })

    it('opens each list on the Display default sort, and a header click sorts only that visit', async () => {
        userLogic.actions.loadUserSuccess({
            ...userLogic.values.user!,
            ui_configuration: { version: 1, sql_editor: { vim_mode_enabled: true } },
        })
        const logic = analyticsListLogic()
        logic.mount()
        await expectLogic(logic, () => router.actions.push(urls.analyticsList())).toFinishAllListeners()
        expect(logic.values.feedQuery.orderBy).toBe('-last_viewed_at')

        await expectLogic(logic, () => logic.actions.setFilters({ orderBy: '-created_at' })).toFinishAllListeners()
        expect(logic.values.feedQuery.orderBy).toBe('-created_at')
        await expectLogic(logic, () => router.actions.push(urls.analyticsMine())).toFinishAllListeners()
        expect(logic.values.feedQuery.orderBy).toBe('-last_viewed_at')

        await expectLogic(logic, () => logic.actions.setDefaultSort('-created_at')).toFinishAllListeners()
        expect(logic.values.feedQuery.orderBy).toBe('-created_at')
        expect(capture).toHaveBeenCalledWith('analytics default sort changed', {
            order_by: '-created_at',
            scope: 'mine',
        })
        await expectLogic(logic, () => router.actions.push(urls.analyticsList())).toFinishAllListeners()
        expect(logic.values.feedQuery.orderBy).toBe('-created_at')
        expect(userLogic.values.user?.ui_configuration).toEqual({
            version: 1,
            sql_editor: { vim_mode_enabled: true },
            analytics_list: { default_sort: '-created_at' },
        })
    })

    it('hides insights from All in both scopes, keeps them under the insight type, and remembers the choice', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        await expectLogic(logic, () => router.actions.push(urls.analyticsList())).toFinishAllListeners()
        expect(logic.values.items.map((item) => item.id)).toEqual(expect.arrayContaining(['i1', 'n1']))

        await expectLogic(logic, () => logic.actions.setInsightsHidden(true)).toFinishAllListeners()
        expect(logic.values.items.map((item) => item.id)).toEqual(['n1'])
        expect(capture).toHaveBeenCalledWith('analytics insights toggled', {
            hidden: true,
            scope: 'all',
            folder: false,
        })

        await expectLogic(logic, () => logic.actions.setFilters({ types: ['insight'] })).toFinishAllListeners()
        expect(logic.values.items.map((item) => item.type)).toContain('insight')
        await expectLogic(logic, () => logic.actions.setInsightsHidden(true)).toFinishAllListeners()
        expect(logic.values.filters.types).toEqual([])

        await expectLogic(logic, () => router.actions.push(urls.analyticsMine())).toFinishAllListeners()
        expect(logic.values.feedQuery.hideInsights).toBe(true)
        logic.unmount()

        const restored = analyticsListLogic()
        restored.mount()
        expect(restored.values.insightsHidden).toBe(true)
    })

    it('loads the list again when a hidden-insights save fails and the old setting comes back', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        await expectLogic(logic, () => router.actions.push(urls.analyticsList())).toFinishAllListeners()

        failSave = true
        await expectLogic(logic, () => {
            logic.actions.setInsightsHidden(true)
            logic.actions.setFilters({ search: 'I' })
        }).toFinishAllListeners()

        expect(logic.values.insightsHidden).toBe(false)
        expect(logic.values.currentFeed.initialized).toBe(true)
        expect(logic.values.items.map((item) => item.type)).toContain('insight')
    })

    it.each([
        ['one type as plain text', { type: 'canvas' }, ['canvas']],
        ['several types', { type: ['canvas', 'notebook'] }, ['canvas', 'notebook']],
        ['no type', {}, []],
        ['an unknown type', { type: ['canvas', 'nonsense'] }, ['canvas']],
    ])('reads %s from the URL', async (_, params, types) => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsList(params))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters.types).toEqual(types)
    })

    it('narrows the feed to every picked type', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        logic.actions.setFilters({ types: ['canvas', 'notebook'] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.feedQuery.types).toEqual(['canvas', 'notebook'])
    })

    it('drops only insights from the picked types when insights get hidden', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        logic.actions.setFilters({ types: ['insight', 'notebook'] })
        logic.actions.setInsightsHidden(true)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters.types).toEqual(['notebook'])
    })

    it('shows no matches, not a load error, for a tag on types that carry no tags', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        logic.actions.setFilters({ types: ['canvas'], tags: ['weekly'] })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.listState).toBe('no-matches')
    })

    it('refreshes view times when URL filters restore a cached sorted list', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsList({ orderBy: '-last_viewed_at' }))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.items[0].entry?.last_viewed_at).toBeNull()
        router.actions.push(urls.analyticsList({ type: 'notebook' }))
        await expectLogic(logic).toFinishAllListeners()
        lastViewedAt = '2026-09-02T00:00:00Z'
        router.actions.push(urls.analyticsList({ orderBy: '-last_viewed_at' }))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.items[0].entry?.last_viewed_at).toBe(lastViewedAt)
    })

    it('reports scope switches and item opens with the scope they happened in', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsMine())
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.itemOpened({ type: 'insight', id: 'i1', name: 'I1' } as AnalyticsItem, 3)
        await expectLogic(logic).toFinishAllListeners()

        const events = capture.mock.calls
            .filter(([name]) => name !== '$pageview')
            .map(([name, properties]) => [name, properties?.scope])
        expect(events).toContainEqual(['views scope changed', 'mine'])
        expect(events).toContainEqual(['views list item opened', 'mine'])
        expect(events).toContainEqual(['views list loaded', 'mine'])
    })

    it('reports a folder visit once, however it starts, and a space only when it changes', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsList({ folder: 'Growth' }))
        await expectLogic(logic).toFinishAllListeners()
        router.actions.push(urls.analyticsList({ folder: 'Growth' }))
        await expectLogic(logic).toFinishAllListeners()

        const events = capture.mock.calls
            .filter(([name]) => name !== '$pageview')
            .map(([name, properties]) => [name, properties?.mode ?? properties?.nested])
        expect(events).toEqual([
            ['views list loaded', 'folder'],
            ['analytics collection opened', false],
            ['views list loaded', 'folder'],
        ])
    })

    it('keeps My work on one query when the user record reloads, so the list does not render again', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsMine())
        await expectLogic(logic).toFinishAllListeners()
        const query = logic.values.feedQuery

        userLogic.actions.loadUserSuccess({ ...userLogic.values.user! })

        expect(query.createdByMe).toBe(true)
        expect(query.orderBy).toBe('-last_viewed_at')
        expect(logic.values.feedQuery).toBe(query)
    })

    it.each([
        ['a number', { search: '4' }, { search: '4' }],
        ['a boolean word', { search: 'true' }, { search: 'true' }],
        ['text shaped like a list', { search: '[draft]' }, { search: '[draft]' }],
        ['a collection named with a number', { folder: '2024' }, { folder: '2024' }],
    ])('reads %s back from the URL as the text that was typed', async (_, params, expected) => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsList(params))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filters).toMatchObject(expected)
    })

    it('keeps a typed space once the search reaches the URL', async () => {
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsList())
        logic.actions.setSearchInput('pageview ')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams.search).toBe('pageview ')
        expect(logic.values.searchInput).toBe('pageview ')
    })
})
