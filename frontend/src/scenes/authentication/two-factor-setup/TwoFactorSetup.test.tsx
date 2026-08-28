import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

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

    it('syncs a password-manager autofill into the form on blur', async () => {
        const input = renderSetup()

        // A password manager writes the field without firing a React change event. Setting the DOM
        // value directly mimics that fill; only blur then reaches the form store.
        input.value = '123 456'
        fireEvent.blur(input)

        await expectLogic(twoFactorLogic).toMatchValues({ token: { token: '123456' } })
    })

    it('strips non-digits as the user types', async () => {
        const input = renderSetup()

        fireEvent.change(input, { target: { value: '12 34 56' } })

        await expectLogic(twoFactorLogic).toMatchValues({ token: { token: '123456' } })
    })
})
