import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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

    function renderSetup(): HTMLInputElement {
        const { container } = render(
            <Provider>
                <TwoFactorSetup onSuccess={jest.fn()} />
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

    it('strips non-digits as the user types', async () => {
        const input = renderSetup()

        fireEvent.change(input, { target: { value: '12 34 56' } })

        await expectLogic(twoFactorLogic).toMatchValues({ token: { token: '123456' } })
    })

    it('points the QR code at a new image URL for each new secret', async () => {
        let secretCount = 0
        useMocks({
            get: {
                '/api/users/@me/two_factor_start_setup/': () => [
                    200,
                    { success: true, secret: `SECRET${++secretCount}` },
                ],
            },
        })
        renderSetup()
        const qrCodeSources: string[] = []

        for (const _ of [1, 2]) {
            await expectLogic(twoFactorLogic, () => {
                twoFactorLogic.actions.openTwoFactorSetupModal()
            }).toDispatchActions(['openTwoFactorSetupModalSuccess'])
            qrCodeSources.push(screen.getByAltText('QR code for two-factor authentication setup').getAttribute('src')!)
            twoFactorLogic.actions.closeTwoFactorSetupModal()
        }

        expect(new Set(qrCodeSources).size).toBe(2)
    })
})
