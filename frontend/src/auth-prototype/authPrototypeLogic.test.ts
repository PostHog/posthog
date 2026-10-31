import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'

import { handleLoginRedirect } from 'scenes/authentication/auth/loginLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { authPrototypeLogic } from './authPrototypeLogic'

jest.mock('scenes/authentication/auth/loginLogic', () => ({ handleLoginRedirect: jest.fn() }))

describe('authPrototypeLogic', () => {
    const originalLocation = window.location
    const replace = jest.fn()
    let logic: ReturnType<typeof authPrototypeLogic.build>

    beforeEach(() => {
        initKeaTests(false)
        router.actions.push('/login?auth_app=standalone')
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: { ...originalLocation, replace },
        })
        replace.mockClear()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(null)
        jest.mocked(handleLoginRedirect).mockClear()
        logic = authPrototypeLogic()
    })

    afterEach(() => {
        logic.unmount()
        userLogic.unmount()
        Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
    })

    it.each(['/login', '/login/', '/login?auth_app=standalone'])('keeps %s in the prototype', (url) => {
        logic.mount()
        router.actions.push(url)
        expect(replace).not.toHaveBeenCalled()
    })

    it.each(['/login/2fa?next=%2Fproject%2F1', '/reset', '/verify_email/example'])('hands %s back to Django', (url) => {
        logic.mount()
        window.location.href = `${originalLocation.origin}${url}`
        router.actions.push(url)
        expect(replace).toHaveBeenCalledWith(`${originalLocation.origin}${url}`)
    })

    it('does not redirect without a user', () => {
        logic.mount()
        userLogic.actions.loadUserSuccess(null)

        expect(handleLoginRedirect).not.toHaveBeenCalled()
    })

    it.each([false, true])('redirects once when user is preloaded: %s', (preloaded) => {
        if (preloaded) {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        }
        logic.mount()
        if (!preloaded) {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        }
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

        expect(handleLoginRedirect).toHaveBeenCalledTimes(1)
    })
})
