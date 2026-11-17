import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'

import { getPageNewEventsTable } from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { newEventsTableLogic } from './newEventsTableLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    ...jest.requireActual('lib/api'),
    getPageNewEventsTable: jest.fn(),
}))

describe('newEventsTableLogic', () => {
    const originalLocation = window.location
    let reload: jest.Mock

    beforeEach(() => {
        document.cookie = 'ph_new_events_schema=; path=/; max-age=0'
        jest.mocked(getPageNewEventsTable).mockReturnValue(null)
        reload = jest.fn()
        Object.defineProperty(window, 'location', { value: { reload }, configurable: true })
        initKeaTests()
    })

    afterEach(() => {
        Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
    })

    function mountAs(user: Partial<UserType>): ReturnType<typeof newEventsTableLogic.build> {
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, ...user })
        const logic = newEventsTableLogic()
        logic.mount()
        return logic
    }

    it.each([
        { session: 'a staff user', user: { is_staff: true, is_impersonated: false }, acts: true },
        { session: 'an impersonated session', user: { is_staff: false, is_impersonated: true }, acts: true },
        { session: 'a regular user', user: { is_staff: false, is_impersonated: false }, acts: false },
    ])('a page loaded from a link to the new table, opened by $session', ({ user, acts }) => {
        jest.mocked(getPageNewEventsTable).mockReturnValue(true)

        const logic = mountAs(user)

        expect(logic.values.newEventsTableActive).toBe(acts)
        expect(document.cookie).not.toContain('ph_new_events_schema')
        expect(reload).not.toHaveBeenCalled()
    })

    it.each([
        { cookie: false, page: true, enabled: true },
        { cookie: true, page: false, enabled: false },
    ])('a page loaded for the new table $page beats a browser cookie of $cookie', ({ cookie, page, enabled }) => {
        if (cookie) {
            document.cookie = 'ph_new_events_schema=1; path=/'
        }
        jest.mocked(getPageNewEventsTable).mockReturnValue(page)

        const logic = mountAs({ is_staff: true })

        expect(logic.values.newEventsTableEnabled).toBe(enabled)
    })

    it("switching back clears the cookie and the page's choice, and reloads", () => {
        document.cookie = 'ph_new_events_schema=1; path=/'
        jest.mocked(getPageNewEventsTable).mockReturnValue(true)
        router.actions.push('/insights', { ph_new_events_schema: '1', other: 'kept' })
        const logic = mountAs({ is_staff: true })

        logic.actions.setNewEventsTable(false)

        expect(document.cookie).not.toContain('ph_new_events_schema')
        expect(router.values.searchParams).toEqual({ other: 'kept' })
        expect(logic.values.newEventsTableActive).toBe(false)
        expect(reload).toHaveBeenCalledTimes(1)
    })

    it.each([
        { enabled: true, value: '1' },
        { enabled: false, value: '0' },
    ])('opens the same page in a new tab on table $value', ({ enabled, value }) => {
        const open = jest.spyOn(window, 'open').mockReturnValue(null)
        router.actions.push('/dashboard/1', { date_from: '-7d' })
        const logic = mountAs({ is_staff: true })

        logic.actions.openEventsTableTab(enabled)

        expect(open).toHaveBeenCalledWith(
            `${router.values.location.pathname}?date_from=-7d&ph_new_events_schema=${value}`,
            '_blank',
            'noopener'
        )
        expect(router.values.location.pathname).toMatch(/\/dashboard\/1$/)
        open.mockRestore()
    })

    it('dismissing the bar keeps the table on, and switching again shows the bar again', () => {
        document.cookie = 'ph_new_events_schema=1; path=/'
        const logic = mountAs({ is_staff: true })

        logic.actions.dismissNewEventsTableBar()

        expect(logic.values.newEventsTableBarDismissed).toBe(true)
        expect(logic.values.newEventsTableActive).toBe(true)
        expect(reload).not.toHaveBeenCalled()

        logic.actions.setNewEventsTable(true)

        expect(logic.values.newEventsTableBarDismissed).toBe(false)
    })
})
