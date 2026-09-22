import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { twoFactorLogic } from './twoFactorLogic'
import { TwoFactorSetup } from './TwoFactorSetup'

describe('TwoFactorSetup', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    function renderSetup(onSuccess: () => void = jest.fn()): HTMLInputElement {
        const { container } = render(
            <Provider>
                <TwoFactorSetup onSuccess={onSuccess} />
            </Provider>
        )
        return container.querySelector<HTMLInputElement>('input[data-attr="token"]')!
    }

    // A password manager can fill the field without a React change event, so the store only catches
    // up when the field commits: blur on a mouse submit, or Enter through the form's implicit submit.
    const commitTriggers: [string, (input: HTMLInputElement) => void][] = [
        ['blur', (input) => fireEvent.blur(input)],
        ['pressing Enter', (input) => fireEvent.keyDown(input, { key: 'Enter' })],
    ]

    it.each(commitTriggers)('syncs a password-manager autofill into the form on %s', async (_label, commit) => {
        const input = renderSetup()

        // Set the DOM value directly to mimic the autofill, then commit without a change event.
        input.value = '123 456'
        commit(input)

        await expectLogic(twoFactorLogic).toMatchValues({ token: { token: '123456' } })
    })

    it('shows the backup codes and holds setup open until the user confirms them', async () => {
        useMocks({
            post: {
                '/api/users/@me/two_factor_validate/': () => [200, { success: true, backup_codes: ['aaa', 'bbb'] }],
            },
            get: { '/api/users/@me/two_factor_status/': () => [200, { is_enabled: true, backup_codes: [] }] },
        })
        const onSuccess = jest.fn()
        const input = renderSetup(onSuccess)

        fireEvent.change(input, { target: { value: '123456' } })
        fireEvent.click(screen.getByRole('button', { name: 'Submit' }))

        await waitFor(() => expect(screen.getByText('aaa')).toBeInTheDocument())
        expect(onSuccess).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole('button', { name: "I've saved my backup codes" }))

        expect(onSuccess).toHaveBeenCalled()
    })

    it('strips non-digits as the user types', async () => {
        const input = renderSetup()

        fireEvent.change(input, { target: { value: '12 34 56' } })

        await expectLogic(twoFactorLogic).toMatchValues({ token: { token: '123456' } })
    })
})
