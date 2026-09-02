import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Signup } from './Signup'

describe('Signup', () => {
    let signupRequestBody: Record<string, any> | null

    beforeEach(() => {
        signupRequestBody = null
        useMocks({
            get: {
                // The form only renders for a logged-out user
                '/api/users/@me/': () => [401, { detail: 'Not authenticated' }],
            },
            post: {
                '/api/signup/precheck': () => [200, { email_exists: false, pending_invite: null }],
                // 400 rather than 201 so the submit handler never assigns `location.href`,
                // which jsdom does not implement. The request body is captured before the response.
                '/api/signup/': async (info) => {
                    signupRequestBody = (await info.request.clone().json()) as Record<string, any>
                    return [400, { type: 'validation_error', code: 'error', detail: 'Mocked failure', attr: null }]
                },
            },
        })
        // initKeaTests bootstraps a logged-in user unless current_user is pre-set; the
        // form only renders logged-out
        window.POSTHOG_APP_CONTEXT = { current_user: null } as any
        initKeaTests()
        router.actions.push('/signup')
        render(
            <Provider>
                <Signup />
            </Provider>
        )
    })

    afterEach(() => {
        cleanup()
    })

    async function submitEmail(email: string): Promise<void> {
        if (email) {
            await userEvent.type(screen.getByTestId('signup-email'), email)
        }
        await userEvent.click(screen.getByTestId('signup-start'))
    }

    async function submitPassword(password: string): Promise<void> {
        await userEvent.type(await screen.findByTestId('password'), password)
        await userEvent.click(screen.getByTestId('signup-auth-continue'))
    }

    async function fillOnboardingAndSubmit({
        name,
        organizationName,
    }: {
        name: string
        organizationName?: string
    }): Promise<void> {
        await userEvent.type(await screen.findByTestId('signup-name'), name)
        if (organizationName) {
            await userEvent.type(screen.getByTestId('signup-organization-name'), organizationName)
        }
        await userEvent.click(screen.getByTestId('signup-role-at-organization'))
        await userEvent.click(await screen.findByText('Engineering'))
        await userEvent.click(screen.getByTestId('signup-submit'))
    }

    it('submitting without an email shows the error and stays on the email panel', async () => {
        await submitEmail('')

        expect(await screen.findByText('Please enter your email to continue')).toBeVisible()
        expect(screen.getByTestId('signup-email')).toBeInTheDocument()
    })

    it('a too-short password blocks the auth panel; a valid one advances to onboarding', async () => {
        await submitEmail('test@example.com')

        await submitPassword('123')
        expect(await screen.findByTestId('signup-auth-continue')).toHaveAttribute('aria-disabled', 'true')
        expect(screen.queryByTestId('signup-name')).not.toBeInTheDocument()

        await userEvent.clear(screen.getByTestId('password'))
        await submitPassword('Str0ng-Test-Pass!')
        expect(await screen.findByTestId('signup-name')).toBeInTheDocument()
    })

    // The panels are the only place the three forms get wired to the logic, so this walkthrough
    // guards that wiring. The payload shaping itself is covered in signupLogic.test.ts.
    it('walks all three panels and posts what was typed into them', async () => {
        await submitEmail('test@example.com')
        await submitPassword('Str0ng-Test-Pass!')
        await fillOnboardingAndSubmit({ name: 'Alice Bob', organizationName: 'Hogflix SpinOff' })

        await waitFor(() => {
            expect(signupRequestBody).not.toBeNull()
        })
        expect(signupRequestBody?.email).toBe('test@example.com')
        expect(signupRequestBody?.password).toBe('Str0ng-Test-Pass!')
        expect(signupRequestBody?.first_name).toBe('Alice')
        expect(signupRequestBody?.last_name).toBe('Bob')
        expect(signupRequestBody?.organization_name).toBe('Hogflix SpinOff')
    })
})
