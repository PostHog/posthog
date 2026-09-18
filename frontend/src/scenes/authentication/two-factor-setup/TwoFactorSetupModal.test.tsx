import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { twoFactorLogic } from './twoFactorLogic'
import { TwoFactorSetupModal } from './TwoFactorSetupModal'

describe('TwoFactorSetupModal', () => {
    const setupMocks = {
        '/api/users/@me/two_factor_start_setup/': () => [200, { secret: 'SECRET', success: true }],
        '/api/users/@me/two_factor_status/': () => [200, { is_enabled: false, backup_codes: [] }],
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    async function openAndSubmit(): Promise<void> {
        render(
            <Provider>
                <TwoFactorSetupModal />
            </Provider>
        )
        twoFactorLogic.actions.openTwoFactorSetupModal()

        const input = await screen.findByPlaceholderText('123456')
        expect(screen.getByLabelText('close')).toBeInTheDocument()

        fireEvent.change(input, { target: { value: '123456' } })
        fireEvent.click(screen.getByRole('button', { name: 'Submit' }))
    }

    it('cannot be closed while the token is validated', async () => {
        let releaseValidate: () => void = () => {}
        useMocks({
            get: setupMocks,
            post: {
                '/api/users/@me/two_factor_validate/': async () => {
                    await new Promise<void>((resolve) => {
                        releaseValidate = resolve
                    })
                    return [200, { success: true, backup_codes: ['aaa', 'bbb'] }]
                },
            },
        })

        await openAndSubmit()

        // A close here enrolls the user and skips the codes step they have not seen yet.
        await waitFor(() => expect(screen.queryByLabelText('close')).not.toBeInTheDocument())

        releaseValidate()
        await waitFor(() => expect(screen.getByText('aaa')).toBeInTheDocument())
        expect(screen.queryByLabelText('close')).not.toBeInTheDocument()
    })

    it('can be closed again after the token is rejected', async () => {
        useMocks({
            get: setupMocks,
            post: { '/api/users/@me/two_factor_validate/': () => [400, { code: 'invalid', detail: 'Invalid token' }] },
        })

        await openAndSubmit()

        await waitFor(() => expect(screen.getByText('Invalid token')).toBeInTheDocument())
        expect(screen.getByLabelText('close')).toBeInTheDocument()
    })
})
