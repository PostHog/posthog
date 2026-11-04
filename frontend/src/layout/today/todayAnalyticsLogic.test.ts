import { expectLogic } from 'kea-test-utils'

import { fileSystemEntryToAnalytics } from 'scenes/analytics/analyticsUtils'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { DEFAULT_COLLAPSED_SECTIONS, todayAnalyticsLogic } from './todayAnalyticsLogic'

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
            },
        })
        initKeaTests()
        recentItemsModel.mount()
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
            ['insight', 'Signups'],
            ['dashboard', 'Revenue'],
            ['dashboard', 'Costs'],
        ])

        recentItemsModel.actions.loadRecentsSuccess([])
        expect(logic.values.recentAnalytics).toEqual([])
    })
})
