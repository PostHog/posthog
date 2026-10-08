import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DEFAULT_RECENT_FILTERS, TodayRecentFilters } from './todayRecentFilters'
import { recentRefreshIsDue, todaySpacesLogic } from './todaySpacesLogic'

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

    // The plugin that owns the reload reads `document.hidden`, so a test drives that rather than a clock.
    const setPageHidden = (hidden: boolean): void => {
        Object.defineProperty(document, 'hidden', { value: hidden, configurable: true })
        document.dispatchEvent(new Event('visibilitychange'))
    }

    afterEach(() => {
        Object.defineProperty(document, 'hidden', { value: false, configurable: true })
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

    // A session another client started reaches the rail only on a return to the tab, so the reload has to be
    // registered as a disposable. A plain afterMount load passes every other test in this file.
    it.each<[string, number, boolean]>([
        ['reloads Recent once the cooldown has passed', 20_000, true],
        ['keeps the list it has inside the cooldown', 5_000, false],
    ])('a return to the tab %s', async (_, sinceLastLoad, reloads) => {
        initKeaTests()
        const logic = todaySpacesLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRecentTasksSuccess']).toFinishAllListeners()
        // Age the last load instead of running a clock, so the cooldown is the only variable.
        logic.cache.recentTasksLoadedAt = Date.now() - sinceLastLoad

        const expectation = expectLogic(logic, () => {
            setPageHidden(true)
            setPageHidden(false)
        }).toFinishAllListeners()

        await (reloads
            ? expectation.toDispatchActions(['loadRecentTasks'])
            : expectation.toNotHaveDispatchedActions(['loadRecentTasks']))
    })

    it.each<[string, number | undefined, boolean]>([
        ['a rail that has never loaded refreshes', undefined, true],
        ['a return moments later keeps what it has', 14_000, false],
        ['a return once the cooldown passes refreshes', 15_000, true],
    ])('holds a flick between tabs to one Recent request: %s', (_, sinceLastLoad, due) => {
        const now = 1_000_000
        const loadedAt = sinceLastLoad === undefined ? undefined : now - sinceLastLoad

        expect(recentRefreshIsDue(loadedAt, now)).toBe(due)
    })
})
