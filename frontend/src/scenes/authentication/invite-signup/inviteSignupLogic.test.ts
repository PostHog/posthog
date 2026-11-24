import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ErrorCodes, inviteSignupLogic } from './inviteSignupLogic'

const INVITE_ID = '1234'

describe('inviteSignupLogic', () => {
    let logic: ReturnType<typeof inviteSignupLogic.build>
    const originalLocation = window.location

    afterEach(() => {
        Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
    })

    beforeEach(async () => {
        Object.defineProperty(window, 'location', { value: { ...originalLocation }, configurable: true })
        useMocks({
            get: {
                [`/api/signup/${INVITE_ID}/`]: () => [
                    200,
                    { id: INVITE_ID, target_email: 'jane@example.com', organization_name: 'Example' },
                ],
            },
        })
        initKeaTests()
        logic = inviteSignupLogic()
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.prevalidateInvite(INVITE_ID)
        }).toDispatchActions(['prevalidateInviteSuccess'])
    })

    it('shows the name error on touch, before any submit', () => {
        expect(logic.values.signupErrors).toEqual({})

        logic.actions.touchSignupField('first_name')
        expect(logic.values.signupErrors).toEqual({ first_name: 'Please enter your name' })

        logic.actions.setSignupValue('first_name', 'Jane')
        expect(logic.values.signupErrors).toEqual({})
    })

    it.each([false, true])('allows retrying a failed submit (network failure: %s)', async (networkFailure) => {
        let shouldFail = true
        useMocks({
            post: {
                [`/api/signup/${INVITE_ID}/`]: () =>
                    shouldFail
                        ? networkFailure
                            ? HttpResponse.error()
                            : [400, { code: 'invalid_input', detail: 'Something went wrong.' }]
                        : [200, { redirect_url: '/verify_email/test-user/' }],
                '/api/signup/precheck': () => [200, { email_exists: false }],
            },
        })
        logic.actions.setSignupValues({ first_name: 'Jane', password: 'a-long-and-unusual-passphrase-42' })

        await expectLogic(logic, () => {
            logic.actions.submitSignup()
        }).toFinishAllListeners()
        expect(logic.values.signupManualErrors).toEqual({
            generic: networkFailure
                ? {
                      code: 'network_error',
                      detail: "We couldn't reach PostHog. Check your connection and try again. What you've typed will stay in this form.",
                  }
                : { code: 'invalid_input', detail: 'Something went wrong.' },
        })
        expect(logic.values.signup).toMatchObject({ first_name: 'Jane', password: 'a-long-and-unusual-passphrase-42' })
        expect(logic.values.isSignupSubmitting).toBe(false)

        shouldFail = false
        await expectLogic(logic, () => {
            logic.actions.submitSignup()
        }).toFinishAllListeners()
        expect(logic.values.signupManualErrors).toEqual({})
        expect(window.location.href).toBe('/verify_email/test-user/')
    })

    it('sends a lost-response signup to login when the account was created', async () => {
        useMocks({
            post: {
                [`/api/signup/${INVITE_ID}/`]: () => HttpResponse.error(),
                '/api/signup/precheck': () => [409, { code: 'account_exists' }],
            },
        })
        logic.actions.setSignupValues({ first_name: 'Jane', password: 'a-long-and-unusual-passphrase-42' })

        await expectLogic(logic, () => {
            logic.actions.submitSignup()
        }).toFinishAllListeners()

        expect(window.location.href).toBe('/login')
        expect(logic.values.signupManualErrors).toEqual({})
    })

    // An accepted invite is deleted, so reopening its link returns the same 400 as an unknown invite
    it.each([
        { signedIn: true, expectedError: null },
        { signedIn: false, expectedError: ErrorCodes.InvalidInvite },
    ])('handles a missing invite when signed in is $signedIn', async ({ signedIn, expectedError }) => {
        useMocks({
            get: {
                '/api/signup/used-invite/': () => [
                    400,
                    { code: 'invalid_input', detail: 'The provided invite ID is not valid.' },
                ],
            },
        })
        userLogic.actions.loadUserSuccess(signedIn ? MOCK_DEFAULT_USER : null)
        router.actions.push('/signup/used-invite')

        await expectLogic(logic).toDispatchActions(['prevalidateInviteSuccess'])
        expect(logic.values.error?.code ?? null).toEqual(expectedError)
        expect(router.values.location.pathname.startsWith('/signup')).toBe(!signedIn)
    })
})
