import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PasswordResetComplete } from './PasswordResetComplete'
import { passwordResetLogic } from './passwordResetLogic'

describe('PasswordResetComplete', () => {
    const resetRequest = jest.fn(() => [200, { success: true, email: 'user@example.com' }])

    beforeEach(() => {
        resetRequest.mockClear()
        useMocks({
            get: { '/api/reset/:uuid/': () => [200, {}] },
            post: { '/api/reset/:uuid/': resetRequest },
        })
        initKeaTests()
        router.actions.push('/reset/valid_user/valid_token')
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the mismatch error and does not send the reset when the passwords differ', async () => {
        const { container } = render(
            <Provider>
                <PasswordResetComplete />
            </Provider>
        )
        await expectLogic(passwordResetLogic).toDispatchActions(['validateResetTokenSuccess'])

        fireEvent.change(container.querySelector('input[data-attr="password"]')!, {
            target: { value: 'hedgE-hog-123%' },
        })
        fireEvent.change(container.querySelector('input[data-attr="password-confirm"]')!, {
            target: { value: '1234567A' },
        })
        fireEvent.click(screen.getByText('Change my password'))

        await expectLogic(passwordResetLogic).toDispatchActions(['submitPasswordResetFailure'])
        expect(await screen.findByText('Passwords do not match')).toBeInTheDocument()
        expect(resetRequest).not.toHaveBeenCalled()
    })
})
