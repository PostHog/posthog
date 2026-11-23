import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { analyticsPinnedLogic } from './analyticsPinnedLogic'

describe('analyticsPinnedLogic', () => {
    let requests: string[]

    beforeEach(() => {
        requests = []
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const type = params.get('type') ?? params.get('type__startswith')
                    if (type) {
                        requests.push(`list ${type}`)
                    }
                    return { results: [], count: 0, next: null }
                },
                '/api/projects/:team_id/file_system_shortcut/': {
                    results: [
                        { id: 'sc-product', type: 'session_replay', path: 'Session replay', href: '/replay' },
                        { id: 'sc-home', type: 'folder', path: 'Ada', ref: 'Users/Ada' },
                        { id: 'sc-growth', type: 'folder', path: 'Growth', ref: 'Growth' },
                        { id: 'sc-insight', type: 'insight/trends', path: 'Signups', ref: 'abc123' },
                        { id: 'sc-dashboard', type: 'dashboard', path: 'KPIs', ref: '7', href: '/dashboard/7' },
                    ],
                },
            },
            post: {
                '/api/projects/:team_id/file_system_shortcut/': async ({ request }) => {
                    const body = (await request.json()) as { type: string; ref: string; path: string }
                    requests.push(`create ${body.type}:${body.ref}`)
                    return [201, { id: 'sc-new', ...body }]
                },
                '/api/projects/:team_id/file_system_shortcut/reorder/': async ({ request }) => {
                    const { ordered_ids } = (await request.json()) as { ordered_ids: string[] }
                    requests.push(`reorder ${ordered_ids.join(',')}`)
                    return [200, []]
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
    })

    it('keeps only analytics items and collections, and unpins an item whatever subtype it was pinned as', async () => {
        const logic = analyticsPinnedLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])

        expect(logic.values.pinnedAnalytics.map((pinned) => pinned.key)).toEqual([
            'folder:Growth',
            'insight:abc123',
            'dashboard:7',
        ])

        await expectLogic(logic, () =>
            sidebarPinsLogic.actions.togglePinned({ type: 'insight', ref: 'abc123', name: 'Signups' })
        ).toDispatchActions(projectTreeDataLogic, ['deleteShortcutSuccess'])
        expect(requests).toEqual(['delete sc-insight'])
        expect(logic.values.pinnedAnalytics.map((pinned) => pinned.key)).toEqual(['folder:Growth', 'dashboard:7'])
        expect(sidebarPinsLogic.values.recentlyPinnedKey).toBeNull()
    })

    it('marks a new pin for the sidebar to slide in, under the key its sidebar row carries', async () => {
        const logic = analyticsPinnedLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])

        await expectLogic(logic, () =>
            sidebarPinsLogic.actions.togglePinned({
                type: 'notebook',
                ref: 'nb1',
                name: 'Launch notes',
                href: '/notebooks/nb1',
            })
        ).toDispatchActions(projectTreeDataLogic, ['addShortcutItemSuccess'])
        expect(requests).toEqual(['create notebook:nb1'])
        const added = logic.values.pinnedAnalytics.at(-1)
        expect(added?.key).toBe('notebook:nb1')
        expect(sidebarPinsLogic.values.recentlyPinnedKey).toBe(added?.key)

        sidebarPinsLogic.actions.clearRecentlyPinned()
        expect(sidebarPinsLogic.values.recentlyPinnedKey).toBeNull()
    })

    it('moves a pin among the other pins and leaves the shortcuts that are not analytics in place', async () => {
        const logic = analyticsPinnedLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])

        await expectLogic(logic, () =>
            sidebarPinsLogic.actions.movePinned('sc-dashboard', 'sc-growth')
        ).toDispatchActions(projectTreeDataLogic, ['reorderShortcutsSuccess'])
        expect(requests).toEqual(['reorder sc-product,sc-home,sc-dashboard,sc-growth,sc-insight'])
        expect(logic.values.pinnedAnalytics.map((pinned) => pinned.key)).toEqual([
            'dashboard:7',
            'folder:Growth',
            'insight:abc123',
        ])
    })

    it('shows the pin hint until it is closed or something is pinned', async () => {
        const logic = analyticsPinnedLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])

        await expectLogic(logic, () => logic.actions.showPinHint()).toMatchValues({ pinHintVisible: true })
        await expectLogic(logic, () => logic.actions.hidePinHint()).toMatchValues({ pinHintVisible: false })

        logic.actions.showPinHint()
        await expectLogic(logic, () =>
            sidebarPinsLogic.actions.togglePinned({
                type: 'dashboard',
                ref: '9',
                name: 'Revenue',
                href: '/dashboard/9',
            })
        )
            .toDispatchActions(projectTreeDataLogic, ['addShortcutItem'])
            .toMatchValues({ pinHintVisible: false })
    })

    it('checks only the types View all lists, and tries a failed check again on the next navigation', async () => {
        let failList = true
        useMocks({
            get: {
                '/api/projects/:team_id/file_system_shortcut/': { results: [] },
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const type = params.get('type') ?? params.get('type__startswith')
                    if (!type) {
                        return { results: [], count: 0, next: null }
                    }
                    requests.push(`list ${type}`)
                    if (failList) {
                        return [500, { detail: 'Server error' }]
                    }
                    const results = type === 'insight' ? [{ id: 'fs-1', type: 'insight/trends', ref: 'abc123' }] : []
                    return { results, count: results.length, next: null }
                },
            },
        })
        userLogic.actions.loadUserSuccess({
            ...userLogic.values.user!,
            ui_configuration: { version: 1, analytics_list: { hide_insights: true } },
        })
        const logic = analyticsPinnedLogic()

        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadHasAnalyticsItemsFailure'])
        expect(logic.values.hasAnalyticsItems).toBeNull()

        failList = false
        requests = []
        await expectLogic(logic, () => router.actions.push('/analytics/all'))
            .toDispatchActions(['loadHasAnalyticsItemsSuccess'])
            .toMatchValues({ hasAnalyticsItems: false })
        expect(requests).not.toContain('list insight')
        expect(requests.length).toBeGreaterThan(0)
    })
})
