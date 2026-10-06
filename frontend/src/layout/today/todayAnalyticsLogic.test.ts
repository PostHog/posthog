import { useMocks } from '~/mocks/jest'
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
    })

    it('starts with only the folders closed, and remembers a toggled section', () => {
        const logic = todayAnalyticsLogic()
        logic.mount()
        expect(logic.values.collapsedSections).toEqual(DEFAULT_COLLAPSED_SECTIONS)
        expect(logic.values.collapsedSections).toEqual(['folders'])

        logic.actions.toggleSection('browse')
        expect(logic.values.collapsedSections).toEqual(['folders', 'browse'])

        logic.unmount()
        const remounted = todayAnalyticsLogic()
        remounted.mount()
        expect(remounted.values.collapsedSections).toEqual(['folders', 'browse'])
    })
})
