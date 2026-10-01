import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DEFAULT_RECENT_FILTERS, TodayRecentFilters } from './todayRecentFilters'
import { todaySpacesLogic } from './todaySpacesLogic'

const SAVED_FILTERS_KEY = 'layout.today.todaySpacesLogic.recentFilters'

describe('todaySpacesLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/task_activity/': { results: [] },
                '/api/projects/:team_id/tasks/': { results: [], count: 0 },
            },
        })
    })

    it.each<[string, object, Partial<TodayRecentFilters>, boolean]>([
        ['an untouched menu stays clear', { createdBy: 'anyone', sources: [] }, {}, false],
        [
            'a saved choice stays',
            { createdBy: 'me', sources: ['slack'] },
            { createdBy: 'me', sources: ['slack'] },
            true,
        ],
    ])('reads Recent filters saved before Status, Pinned and Environment: %s', (_, saved, expected, active) => {
        localStorage.setItem(SAVED_FILTERS_KEY, JSON.stringify(saved))
        initKeaTests()
        const logic = todaySpacesLogic()
        logic.mount()

        expect(logic.values.recentFilters).toEqual({ ...DEFAULT_RECENT_FILTERS, ...expected })
        expect(logic.values.recentFiltersActive).toBe(active)
    })
})
