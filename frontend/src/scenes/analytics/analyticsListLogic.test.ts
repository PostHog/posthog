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

    beforeEach(() => {
        localStorage.clear()
        lastViewedAt = null
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

    it('ignores saved defaults and remembers explicit sort choices separately for both scopes', async () => {
        localStorage.setItem(
            '997__u-ada__.scenes.analytics.analyticsListLogic.orderByByScope',
            JSON.stringify({ mine: '-last_viewed_at', all: '-created_at' })
        )
        const logic = analyticsListLogic()
        logic.mount()
        router.actions.push(urls.analyticsMine())
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.feedQuery.orderBy).toBe('-last_viewed_at')
        logic.actions.setFilters({ orderBy: 'last_viewed_at' })
        await expectLogic(logic).toFinishAllListeners()
        router.actions.push(urls.analyticsList())
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.feedQuery.orderBy).toBe('-last_viewed_at')
        router.actions.push(urls.analyticsMine())
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.feedQuery.orderBy).toBe('last_viewed_at')
        logic.unmount()

        const restored = analyticsListLogic()
        restored.mount()
        await expectLogic(restored, () => router.actions.push(urls.analyticsList())).toFinishAllListeners()
        expect(restored.values.feedQuery.orderBy).toBe('-last_viewed_at')
        await expectLogic(restored, () =>
            restored.actions.setFilters({ orderBy: '-created_at' })
        ).toFinishAllListeners()
        restored.unmount()

        const withSavedChoice = analyticsListLogic()
        withSavedChoice.mount()
        await expectLogic(withSavedChoice, () => withSavedChoice.actions.loadList()).toFinishAllListeners()
        expect(withSavedChoice.values.feedQuery.orderBy).toBe('-created_at')
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
