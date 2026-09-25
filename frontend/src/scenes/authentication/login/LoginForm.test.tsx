import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { LoginForm } from './LoginForm'
import { loginLogic } from './loginLogic'

jest.mock('posthog-js')

describe('LoginForm', () => {
    let loginRequests: number

    beforeEach(() => {
        loginRequests = 0
        useMocks({
            post: {
                // Held open, so the click lands while the precheck is still in flight.
                '/api/login/precheck': () => new Promise(() => {}),
                '/api/login': () => {
                    loginRequests += 1
                    return [200, { success: true }]
                },
            },
        })
        initKeaTests()
        loginLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('submits a password filled by a password manager while the precheck is in flight', async () => {
        render(
            <Provider>
                <LoginForm />
            </Provider>
        )

        // A password manager fills each field in one step, which is what starts the precheck.
        fireEvent.change(screen.getByTestId('login-email'), { target: { value: 'user@example.com' } })
        fireEvent.change(screen.getByTestId('password'), { target: { value: 'secret password' } })
        await waitFor(() => expect(loginLogic.values.precheckResponseLoading).toBe(true))

        const submitButton = screen.getByTestId('password-login')
        expect(submitButton).toHaveAttribute('aria-disabled', 'false')

        fireEvent.click(submitButton)

        await waitFor(() => expect(loginRequests).toBe(1))
    })
})
