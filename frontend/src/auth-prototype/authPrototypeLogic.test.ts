import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { authPrototypeLogic } from './authPrototypeLogic'

describe('authPrototypeLogic', () => {
    const originalLocation = window.location
    const replace = jest.fn()
    let unmount: () => void

    beforeEach(() => {
        initKeaTests()
        router.actions.push('/login?auth_app=standalone')
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: { ...originalLocation, replace },
        })
        replace.mockClear()
        unmount = authPrototypeLogic.mount()
    })

    afterEach(() => {
        unmount()
        Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
    })

    it.each(['/login', '/login/', '/login?auth_app=standalone'])('keeps %s in the prototype', (url) => {
        router.actions.push(url)
        expect(replace).not.toHaveBeenCalled()
    })

    it.each(['/login/2fa?next=%2Fproject%2F1', '/reset', '/verify_email/example'])('hands %s back to Django', (url) => {
        window.location.href = `${originalLocation.origin}${url}`
        router.actions.push(url)
        expect(replace).toHaveBeenCalledWith(`${originalLocation.origin}${url}`)
    })
})
