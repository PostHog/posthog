import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION_MEMBER, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ImpersonationNotice } from './ImpersonationNotice'

const currentUser = {
    ...MOCK_DEFAULT_USER,
    id: 7,
    email: 'current@example.com',
    is_impersonated: true,
    is_impersonated_read_only: false,
    is_impersonated_until: undefined,
}
const nextUser = {
    ...MOCK_DEFAULT_BASIC_USER,
    id: 42,
    uuid: 'next-user',
    first_name: 'Alex',
    last_name: 'Example',
    email: 'alex@example.com',
}

describe('ImpersonationNotice', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/users/@me/': () => [200, currentUser],
                '/api/organizations/:org/members/': () => [
                    200,
                    { results: [{ ...MOCK_DEFAULT_ORGANIZATION_MEMBER, user: nextUser }], next: null },
                ],
                '/admin/auth_check': () => [200, {}],
            },
        })
        userLogic.mount()
        userLogic.actions.loadUserSuccess(currentUser)
    })

    afterEach(cleanup)

    it.each([200, 403])('keeps the selected user modal open after login responds with %s', async (status) => {
        let finishLogin!: () => void
        let finishProbe!: () => void
        let markProbeStarted!: () => void
        const login = new Promise<void>((resolve) => (finishLogin = resolve))
        const probe = new Promise<void>((resolve) => (finishProbe = resolve))
        const probeStarted = new Promise<void>((resolve) => (markProbeStarted = resolve))
        const originalLocation = window.location
        const reload = jest.fn()
        Object.defineProperty(window, 'location', { configurable: true, value: { ...originalLocation, reload } })

        try {
            render(<ImpersonationNotice />)
            fireEvent.click(screen.getByText('current@example.com'))
            fireEvent.click(await screen.findByText('Alex Example'))
            fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Investigate a support request' } })

            useMocks({
                post: {
                    '/admin/login/user/42/': async () => {
                        await login
                        return [status, { success: status === 200 }]
                    },
                },
                get: {
                    '/api/users/@me/': async () => {
                        markProbeStarted()
                        await probe
                        return [200, { ...currentUser, ...nextUser }]
                    },
                },
            })

            fireEvent.click(screen.getByText('Switch user', { selector: 'button span' }))
            expect(screen.getByRole('dialog')).not.toHaveClass('ReactModal__Content--before-close')
            expect(screen.getByText('Cancel').closest('button')).toHaveAttribute('aria-disabled', 'true')
            await act(async () => finishLogin())

            if (status === 200) {
                await act(async () => probeStarted)
                expect(screen.getByRole('dialog')).not.toHaveClass('ReactModal__Content--before-close')
                expect(screen.getByText('Cancel').closest('button')).toHaveAttribute('aria-disabled', 'true')
                expect(reload).not.toHaveBeenCalled()
                await act(async () => finishProbe())
                await waitFor(() => expect(reload).toHaveBeenCalled())
            } else {
                await waitFor(() =>
                    expect(
                        screen.getByText('Switch user', { selector: 'button span' }).closest('button')
                    ).toHaveAttribute('aria-disabled', 'false')
                )
                expect(screen.getByRole('dialog')).not.toHaveClass('ReactModal__Content--before-close')
                expect(screen.getByLabelText('Reason')).toHaveValue('Investigate a support request')
                expect(screen.getByText('Cancel').closest('button')).toHaveAttribute('aria-disabled', 'false')
                expect(reload).not.toHaveBeenCalled()
            }
        } finally {
            finishLogin()
            finishProbe()
            Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
        }
    })
})
