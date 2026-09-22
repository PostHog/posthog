import { startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { passkeySettingsLogic } from './passkeySettingsLogic'

jest.mock('@simplewebauthn/browser', () => ({
    startRegistration: jest.fn(),
    startAuthentication: jest.fn(),
}))

const startRegistrationMock = startRegistration as jest.Mock
const startAuthenticationMock = startAuthentication as jest.Mock

const REGISTRATION_OPTIONS = {
    rp: { id: 'localhost', name: 'PostHog' },
    user: { id: 'dXNlcg', name: 'user@example.com', displayName: 'User' },
    challenge: 'Y2hhbGxlbmdl',
    pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
    timeout: 300000,
    excludeCredentials: [],
    authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
    attestation: 'none',
}

describe('passkeySettingsLogic', () => {
    let logic: ReturnType<typeof passkeySettingsLogic.build>
    let beginRequestCount: number
    let beginRequestsWhenPromptOpened: number | null

    beforeEach(() => {
        beginRequestCount = 0
        beginRequestsWhenPromptOpened = null
        startRegistrationMock.mockReset()
        startAuthenticationMock.mockReset()
        startRegistrationMock.mockImplementation(async () => {
            beginRequestsWhenPromptOpened = beginRequestCount
            return { id: 'credential', response: {} }
        })
        useMocks({
            get: {
                '/api/webauthn/credentials/': () => [200, []],
            },
            post: {
                '/api/webauthn/register/begin': () => {
                    beginRequestCount += 1
                    return [200, REGISTRATION_OPTIONS]
                },
                '/api/webauthn/register/complete': () => [
                    200,
                    { success: true, message: 'Credential stored.', credential_id: '42' },
                ],
            },
        })
        initKeaTests()
        logic = passkeySettingsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens the browser prompt without spending the click on a request first', async () => {
        logic.actions.prepareRegistration()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.beginRegistration('My passkey')
        await expectLogic(logic).toFinishAllListeners()

        expect(beginRequestsWhenPromptOpened).toEqual(1)
    })

    it('joins the prefetch already in flight instead of replacing its challenge', async () => {
        let releaseBegin = (): void => {}
        const beginAnswers = new Promise<void>((resolve) => {
            releaseBegin = resolve
        })
        useMocks({
            post: {
                '/api/webauthn/register/begin': async () => {
                    beginRequestCount += 1
                    await beginAnswers
                    return [200, REGISTRATION_OPTIONS]
                },
                '/api/webauthn/register/complete': () => [
                    200,
                    { success: true, message: 'Credential stored.', credential_id: '42' },
                ],
            },
        })

        logic.actions.prepareRegistration()
        await expectLogic(logic).toMatchValues({ registrationOptionsLoading: true })

        logic.actions.beginRegistration('My passkey')
        releaseBegin()
        await expectLogic(logic).toFinishAllListeners()

        expect(beginRequestsWhenPromptOpened).toEqual(1)
        expect(startRegistrationMock).toHaveBeenCalledTimes(1)
    })

    it('fetches the options itself when no prefetch is in flight', async () => {
        logic.actions.beginRegistration('My passkey')
        await expectLogic(logic).toFinishAllListeners()

        expect(startRegistrationMock).toHaveBeenCalledTimes(1)
        expect(beginRequestsWhenPromptOpened).toEqual(1)
    })

    it('stops after the credential is stored and hands verification back to the user', async () => {
        logic.actions.beginRegistration('My passkey')
        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            registrationStep: 'awaiting_verification',
            pendingVerificationId: 42,
            error: null,
        })

        expect(startAuthenticationMock).not.toHaveBeenCalled()
    })

    it('treats a dismissed prompt as an expected outcome, not an error', async () => {
        startRegistrationMock.mockRejectedValue(new DOMException('cancelled', 'NotAllowedError'))

        logic.actions.beginRegistration('My passkey')
        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            registrationStep: 'idle',
            error: null,
        })
    })
})
