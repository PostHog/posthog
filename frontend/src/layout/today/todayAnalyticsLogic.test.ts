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

    it('lists recently viewed analytics, insights included, and clears them when the shared list loads empty', () => {
        const logic = todayAnalyticsLogic()
        logic.mount()
        const row = (type: string, ref: string, name: string): FileSystemEntry =>
            ({ id: `fs-${ref}`, type, ref, path: `Unfiled/${name}`, meta: {} }) as FileSystemEntry

        recentItemsModel.actions.loadRecentsSuccess([
            row('insight', 'i1', 'Signups'),
            row('feature_flag', 'f1', 'New nav'),
            row('dashboard', '7', 'Revenue'),
        ])
        expect(logic.values.recentAnalytics.map((item) => [item.type, item.name])).toEqual([
            ['insight', 'Signups'],
            ['dashboard', 'Revenue'],
        ])

        recentItemsModel.actions.loadRecentsSuccess([])
        expect(logic.values.recentAnalytics).toEqual([])
    })
})
