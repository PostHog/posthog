import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { twoFactorLogic } from './twoFactorLogic'
import { TwoFactorSetup } from './TwoFactorSetup'

describe('TwoFactorSetup', () => {
    beforeEach(() => {
        useMocks({
            get: { '/api/users/@me/two_factor_start_setup/': () => [200, { success: true, secret: 'SECRET' }] },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    async function renderSetup(): Promise<HTMLInputElement> {
        twoFactorLogic.mount()
        await expectLogic(twoFactorLogic, () => {
            twoFactorLogic.actions.openTwoFactorSetupModal()
        }).toDispatchActions(['loadStartSetupSuccess'])
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
        const input = await renderSetup()

        // Set the DOM value directly to mimic the autofill, then commit without a change event.
        input.value = '123 456'
        commit(input)

        await expectLogic(twoFactorLogic).toMatchValues({ token: { token: '123456' } })
    })

    it('strips non-digits as the user types', async () => {
        const input = await renderSetup()

        fireEvent.change(input, { target: { value: '12 34 56' } })

        await expectLogic(twoFactorLogic).toMatchValues({ token: { token: '123456' } })
    })
})
