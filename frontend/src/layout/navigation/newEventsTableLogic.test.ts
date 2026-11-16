import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'
import { UserType } from '~/types'

import { newEventsTableLogic } from './newEventsTableLogic'

describe('newEventsTableLogic', () => {
    const originalLocation = window.location
    let reload: jest.Mock

    beforeEach(() => {
        document.cookie = 'ph_new_events_schema=; path=/; max-age=0'
        window.sessionStorage.clear()
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
    ])('a link that turns the new table on for its tab, opened by $session', ({ user, acts }) => {
        router.actions.push('/insights', { ph_new_events_schema: '1', other: 'kept' })

        const logic = mountAs(user)

        expect(window.sessionStorage.getItem('ph_new_events_schema')).toBe(acts ? '1' : null)
        expect(document.cookie).not.toContain('ph_new_events_schema')
        expect(reload).toHaveBeenCalledTimes(acts ? 1 : 0)
        expect(Object.keys(router.values.searchParams)).toEqual(acts ? ['other'] : ['ph_new_events_schema', 'other'])
        expect(logic.values.newEventsTableActive).toBe(acts)
    })

    it.each([
        { link: '1', reloads: false, enabled: true },
        { link: '0', reloads: true, enabled: false },
    ])('a link to table $link in a browser on the new table', ({ link, reloads, enabled }) => {
        document.cookie = 'ph_new_events_schema=1; path=/'
        router.actions.push('/insights', { ph_new_events_schema: link })

        const logic = mountAs({ is_staff: true })

        expect(reload).toHaveBeenCalledTimes(reloads ? 1 : 0)
        expect(router.values.searchParams).toEqual({})
        expect(document.cookie).toContain('ph_new_events_schema=1')
        expect(logic.values.newEventsTableEnabled).toBe(enabled)
    })

    it('switching back clears the cookie and the tab choice, and reloads', () => {
        document.cookie = 'ph_new_events_schema=1; path=/'
        window.sessionStorage.setItem('ph_new_events_schema', '1')
        const logic = mountAs({ is_staff: true })
        expect(logic.values.newEventsTableActive).toBe(true)

        logic.actions.setNewEventsTable(false)

        expect(document.cookie).not.toContain('ph_new_events_schema')
        expect(window.sessionStorage.getItem('ph_new_events_schema')).toBeNull()
        expect(logic.values.newEventsTableActive).toBe(false)
        expect(reload).toHaveBeenCalledTimes(1)
    })

    it('opens the same page in a new tab on the other table', () => {
        const open = jest.spyOn(window, 'open').mockReturnValue(null)
        router.actions.push('/dashboard/1', { date_from: '-7d' })
        const logic = mountAs({ is_staff: true })

        logic.actions.openOtherEventsTableTab()

        expect(open).toHaveBeenCalledWith(
            `${router.values.location.pathname}?date_from=-7d&ph_new_events_schema=1`,
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
