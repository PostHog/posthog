import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LoginForm } from './LoginForm'
import { loginLogic } from './loginLogic'

describe('LoginForm', () => {
    let logic: ReturnType<typeof loginLogic.build>
    let releasePrecheck: () => void

    beforeEach(() => {
        useMocks({
            post: {
                // Hold the precheck open so we can observe the form while it is in flight.
                '/api/login/precheck': async () => {
                    await new Promise<void>((resolve) => {
                        releasePrecheck = resolve
                    })
                    return { status: 'completed', saml_available: false, password_login_available: true }
                },
            },
        })
        initKeaTests()
        logic = loginLogic()
        logic.mount()
    })

    afterEach(() => {
        releasePrecheck?.()
        logic.unmount()
        cleanup()
    })

    // A loading LemonButton is disabled, and its click handler calls preventDefault(), which kills the
    // native submit of the enclosing form. Tying the Log in button to the precheck therefore swallows
    // every click while the precheck (fired on email blur/autofill) resolves. Guard that it does not.
    it('keeps the Log in button enabled while a precheck is in flight', async () => {
        const { container } = render(<LoginForm />)

        logic.actions.setLoginValue('email', 'user@example.com')
        logic.actions.precheck({ email: 'user@example.com' })
        await waitFor(() => expect(logic.values.precheckResponseLoading).toBe(true))

        const button = container.querySelector('[data-attr="password-login"]')
        expect(button).toHaveAttribute('aria-disabled', 'false')
    })
})
