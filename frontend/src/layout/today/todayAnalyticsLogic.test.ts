import { expectLogic } from 'kea-test-utils'

import { fileSystemEntryToAnalytics } from 'scenes/analytics/analyticsUtils'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import defaultSidebarFixture from '~/mocks/fixtures/api/today_analytics_sidebar.json'
import { useMocks } from '~/mocks/jest'
import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { AnalyticsSidebarApi } from 'products/today/frontend/generated/api.schemas'

import {
    DEFAULT_ANALYTICS_SIDEBAR,
    DEFAULT_COLLAPSED_SECTIONS,
    selectShownSidebar,
    todayAnalyticsLogic,
} from './todayAnalyticsLogic'

const CUSTOM_SIDEBAR: AnalyticsSidebarApi = {
    customized: true,
    layout: {
        version: 1,
        sections: [
            { id: 'growth', title: 'Growth', items: [{ type: 'metric', insight: 'aB3dE5fG', label: 'Signups' }] },
        ],
    },
}
const DEFAULT_SIDEBAR: AnalyticsSidebarApi = {
    customized: false,
    layout: { version: 1, sections: [{ id: 'pinned', title: 'Pinned', items: [{ type: 'list', source: 'pinned' }] }] },
}

describe('todayAnalyticsLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/canvases/': { results: [], next: null },
                '/api/projects/:team_id/notebooks/': { results: [], next: null },
                '/api/projects/:team_id/dashboards/': { results: [], next: null },
                '/api/projects/:team_id/insights/': { results: [], next: null },
                '/api/projects/:team_id/file_system_shortcut/': {
                    results: [{ id: 'sc-pinned', type: 'insight/trends', path: 'Retention', ref: 'i2' }],
                },
                '/api/projects/:team_id/today/analytics_sidebar/': CUSTOM_SIDEBAR,
            },
            put: { '/api/projects/:team_id/today/analytics_sidebar/': CUSTOM_SIDEBAR },
            delete: { '/api/projects/:team_id/today/analytics_sidebar/': DEFAULT_SIDEBAR },
        })
        initKeaTests()
        recentItemsModel.mount()
    })

    it.each([false, true])('shows the default while the first request is pending, failure=%s', async (fails) => {
        let startRequest!: () => void
        const requestStarted = new Promise<void>((resolve) => (startRequest = resolve))
        let finishRequest!: () => void
        const requestReleased = new Promise<void>((resolve) => (finishRequest = resolve))
        useMocks({
            get: {
                '/api/projects/:team_id/today/analytics_sidebar/': async () => {
                    startRequest()
                    await requestReleased
                    return fails ? [503, { detail: 'Unavailable' }] : [200, CUSTOM_SIDEBAR]
                },
            },
        })
        const logic = todayAnalyticsLogic()
        logic.mount()
        await requestStarted

        expect(DEFAULT_ANALYTICS_SIDEBAR).toEqual(defaultSidebarFixture)
        expect(logic.values.sidebarLayout).toEqual(DEFAULT_ANALYTICS_SIDEBAR.layout)
        expect(logic.values.sidebarCustomized).toBe(false)

        finishRequest()
        await expectLogic(logic).toDispatchActions([fails ? 'loadSidebarFailure' : 'loadSidebarSuccess'])
        expect(logic.values.sidebarFailed).toBe(fails)
        expect(logic.values.sidebarLayout).toEqual(fails ? DEFAULT_ANALYTICS_SIDEBAR.layout : CUSTOM_SIDEBAR.layout)
        expect(logic.values.sidebarCustomized).toBe(!fails)
    })

    it('prefers a server layout over a saved layout, and a saved layout over the default', () => {
        expect(selectShownSidebar(null, null)).toEqual(DEFAULT_ANALYTICS_SIDEBAR)
        expect(selectShownSidebar(null, CUSTOM_SIDEBAR)).toEqual(CUSTOM_SIDEBAR)
        expect(selectShownSidebar(DEFAULT_SIDEBAR, CUSTOM_SIDEBAR)).toEqual(DEFAULT_SIDEBAR)
    })

    it('starts with every section open, and remembers a toggled section', () => {
        const logic = todayAnalyticsLogic()
        logic.mount()
        expect(logic.values.collapsedSections).toEqual(DEFAULT_COLLAPSED_SECTIONS)
        expect(logic.values.collapsedSections).toEqual([])

        logic.actions.toggleSection('monitor')
        expect(logic.values.collapsedSections).toEqual(['monitor'])

        logic.unmount()
        const remounted = todayAnalyticsLogic()
        remounted.mount()
        expect(remounted.values.collapsedSections).toEqual(['monitor'])
    })

    it('lists recently viewed analytics up to the limit, leaving out pinned items, and clears them when the shared list loads empty', async () => {
        const logic = todayAnalyticsLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])
        const row = (type: string, ref: string, name: string): FileSystemEntry =>
            ({ id: `fs-${ref}`, type, ref, path: `Unfiled/${name}`, meta: {} }) as FileSystemEntry

        await expectLogic(logic, () =>
            logic.actions.storeRecentAnalytics(
                [row('insight', 'i1', 'Signups'), row('insight', 'i2', 'Retention')].flatMap(
                    (entry) => fileSystemEntryToAnalytics(entry) ?? []
                )
            )
        )
            .toDispatchActions(['storeRecentAnalytics'])
            .toNotHaveDispatchedActions(['storeRecentAnalytics'])
        expect(logic.values.recentAnalytics.map((item) => item.name)).toEqual(['Signups'])

        recentItemsModel.actions.loadRecentsSuccess([
            row('insight', 'i1', 'Signups'),
            row('insight', 'i2', 'Retention'),
            row('feature_flag', 'f1', 'New nav'),
            row('dashboard', '7', 'Revenue'),
            row('dashboard', '8', 'Costs'),
        ])
        expect(logic.values.recentAnalytics.map((item) => [item.type, item.name])).toEqual([
            ['dashboard', 'Costs'],
            ['dashboard', 'Revenue'],
            ['insight', 'Signups'],
        ])

        recentItemsModel.actions.loadRecentsSuccess([])
        expect(logic.values.recentAnalytics).toEqual([])
    })

    it('shows the saved layout, and puts it back after a reset when asked', async () => {
        const logic = todayAnalyticsLogic()
        logic.mount()
        const shown = (): [boolean, string[] | undefined] => [
            logic.values.sidebarCustomized,
            logic.values.sidebarLayout?.sections.map((section) => section.id),
        ]
        await expectLogic(logic).toDispatchActions(['loadSidebarSuccess'])
        const loaded = shown()

        await expectLogic(logic, () => logic.actions.resetSidebar(CUSTOM_SIDEBAR.layout)).toDispatchActions([
            'resetSidebarSuccess',
        ])
        const reset = shown()

        await expectLogic(logic, () => logic.actions.restoreSidebar(CUSTOM_SIDEBAR.layout)).toDispatchActions([
            'restoreSidebarSuccess',
        ])

        expect([loaded, reset, shown()]).toEqual([
            [true, ['growth']],
            [false, ['pinned']],
            [true, ['growth']],
        ])
    })
})
