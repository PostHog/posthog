import '@testing-library/jest-dom'

import { startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PasskeyAddForm } from './PasskeyAddForm'
import { passkeySettingsLogic } from './passkeySettingsLogic'

jest.mock('@simplewebauthn/browser', () => ({
    startRegistration: jest.fn(),
    startAuthentication: jest.fn(),
}))

const startRegistrationMock = startRegistration as jest.Mock
const startAuthenticationMock = startAuthentication as jest.Mock

describe('PasskeyAddForm', () => {
    beforeEach(() => {
        startRegistrationMock.mockReset().mockResolvedValue({ id: 'credential', response: {} })
        startAuthenticationMock.mockReset().mockResolvedValue({ id: 'credential', response: {} })
        useMocks({
            get: {
                '/api/webauthn/credentials/': () => [200, []],
            },
            post: {
                '/api/webauthn/register/begin': () => [
                    200,
                    {
                        rp: { id: 'localhost', name: 'PostHog' },
                        user: { id: 'dXNlcg', name: 'user@example.com', displayName: 'User' },
                        challenge: 'Y2hhbGxlbmdl',
                        pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
                        timeout: 300000,
                        excludeCredentials: [],
                        authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
                        attestation: 'none',
                    },
                ],
                '/api/webauthn/register/complete': () => [
                    200,
                    { success: true, message: 'Credential stored.', credential_id: '42' },
                ],
                '/api/webauthn/credentials/42/verify': () => [
                    200,
                    {
                        challenge: 'Y2hhbGxlbmdl',
                        timeout: 300000,
                        rpId: 'localhost',
                        allowCredentials: [],
                        userVerification: 'required',
                    },
                ],
                '/api/webauthn/credentials/42/verify_complete': () => [
                    200,
                    { id: 42, label: 'My passkey', created_at: '', transports: [], verified: true },
                ],
            },
        })
        initKeaTests()
        passkeySettingsLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('asks the user to start the verification ceremony with a click of its own', async () => {
        const { container } = render(
            <Provider>
                <PasskeyAddForm />
            </Provider>
        )

        fireEvent.click(screen.getByText('Add passkey'))
        await expectLogic(passkeySettingsLogic).toFinishAllListeners()
        expect(startAuthenticationMock).not.toHaveBeenCalled()

        fireEvent.click(container.querySelector('button[data-attr="verify-new-passkey"]')!)
        await expectLogic(passkeySettingsLogic).toFinishAllListeners().toMatchValues({
            registrationStep: 'complete',
        })
        expect(startAuthenticationMock).toHaveBeenCalledTimes(1)
    })

    it('holds the add controls until the saved passkey is verified or the prompt is dismissed', async () => {
        const { container } = render(
            <Provider>
                <PasskeyAddForm />
            </Provider>
        )
        const addButton = (): HTMLButtonElement => container.querySelector('button.LemonButton--primary')!

        fireEvent.click(screen.getByText('Add passkey'))
        await expectLogic(passkeySettingsLogic).toFinishAllListeners()
        expect(addButton()).toHaveAttribute('aria-disabled', 'true')

        fireEvent.click(container.querySelector('button[aria-label="close"]')!)
        expect(addButton()).toHaveAttribute('aria-disabled', 'false')
    })
})
