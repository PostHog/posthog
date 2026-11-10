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
    ])('a link that turns the new table on, opened by $session', ({ user, acts }) => {
        router.actions.push('/insights', { ph_new_events_schema: '1', other: 'kept' })

        const logic = mountAs(user)

        expect(document.cookie.includes('ph_new_events_schema=1')).toBe(acts)
        expect(reload).toHaveBeenCalledTimes(acts ? 1 : 0)
        expect(Object.keys(router.values.searchParams)).toEqual(acts ? ['other'] : ['ph_new_events_schema', 'other'])
        expect(logic.values.newEventsTableActive).toBe(acts)
    })

    it('a link that matches the cookie strips the parameter without a reload', () => {
        document.cookie = 'ph_new_events_schema=1; path=/'
        router.actions.push('/insights', { ph_new_events_schema: '1' })

        mountAs({ is_staff: true })

        expect(reload).not.toHaveBeenCalled()
        expect(router.values.searchParams).toEqual({})
    })

    it('switching back clears the cookie and reloads', () => {
        document.cookie = 'ph_new_events_schema=1; path=/'
        const logic = mountAs({ is_staff: true })
        expect(logic.values.newEventsTableActive).toBe(true)

        logic.actions.setNewEventsTable(false)

        expect(document.cookie).not.toContain('ph_new_events_schema')
        expect(reload).toHaveBeenCalledTimes(1)
    })
})
