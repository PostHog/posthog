import { setPendingOAuthConnectionCookie } from 'scenes/authentication/shared/pendingOAuthConnection.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { signupLogic } from './signupLogic'

describe('signupLogic — email error surfacing', () => {
    let logic: ReturnType<typeof signupLogic.build>
    let signupErrorBody: Record<string, any>

    beforeEach(() => {
        signupErrorBody = {}
        useMocks({
            post: {
                '/api/signup/precheck': () => [200, { email_exists: false, pending_invite: null }],
                '/api/signup/': () => [400, signupErrorBody],
            },
        })
        initKeaTests()
        router.actions.push('/signup')
        logic = signupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['a field-keyed body', { email: ['There is already an account with this email address.'] }, false],
        [
            'a DRF error body',
            {
                type: 'validation_error',
                code: 'unique',
                detail: 'There is already an account with this email address.',
                attr: 'email',
            },
            true,
        ],
    ])(
        'redirects to the email panel and shows the error when the final POST fails with %s',
        async (_name, body, offersLogin) => {
            signupErrorBody = body
            // Advance through email panel (precheck passes)
            logic.actions.precheckSignupEmail('test@example.com')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.panel).toBe(1)

            // Advance through auth panel (a valid password is required to pass form validation)
            logic.actions.setSignupPanelAuthValue('password', 'Str0ng-Test-Pass!')
            logic.actions.submitSignupPanelAuth()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.panel).toBe(2)

            // Submit onboarding — final POST fails with an email error
            logic.actions.setSignupPanelOnboardingValues({
                name: 'Jane Doe',
                organization_name: 'Hogflix',
                role_at_organization: 'engineer',
                referral_source: '',
                referral_source_ai_prompt: '',
            })
            logic.actions.submitSignupPanelOnboarding()
            await expectLogic(logic).toFinishAllListeners()

            // User should be sent back to step 0 with the email error shown there
            expect(logic.values.panel).toBe(0)
            expect(logic.values.signupEmailError).toBe('There is already an account with this email address.')
            expect(logic.values.signupEmailTaken).toBe(offersLogin)
            // The password picked for this email must not carry over to the next one
            expect(logic.values.signupPanelAuth.password).toBe('')
        }
    )
})

describe('signupLogic — pending invite banner', () => {
    let logic: ReturnType<typeof signupLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/signup/precheck': () => [
                    200,
                    {
                        email_exists: false,
                        pending_invite: { organization_name: 'Acme Corp' },
                    },
                ],
                '/api/signup/resend-invite': () => [200, { sent: true }],
            },
        })
        initKeaTests()
        router.actions.push('/signup')
        logic = signupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('shows the pending invite banner instead of advancing the panel', async () => {
        logic.actions.precheckSignupEmail('alice@acme.com')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInvite).toEqual({ organization_name: 'Acme Corp' })
        expect(logic.values.panel).toBe(0)
    })

    it('advances the panel and clears the banner when no invite is returned', async () => {
        useMocks({
            post: {
                '/api/signup/precheck': () => [200, { email_exists: false, pending_invite: null }],
            },
        })
        logic.actions.precheckSignupEmail('stranger@nowhere.com')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInvite).toBeNull()
        expect(logic.values.panel).toBe(1)
    })

    it('advances the panel when the user dismisses the banner', async () => {
        logic.actions.precheckSignupEmail('alice@acme.com')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInvite).not.toBeNull()
        logic.actions.dismissPendingInvite()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInvite).toBeNull()
        expect(logic.values.panel).toBe(1)
    })

    it('skips the banner when skip_invite_check=1 is on the URL', async () => {
        router.actions.push('/signup', { skip_invite_check: '1' })
        logic.actions.precheckSignupEmail('alice@acme.com')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInvite).toBeNull()
        expect(logic.values.panel).toBe(1)
    })

    it('marks the invite as resent after resendPendingInvite succeeds', async () => {
        logic.actions.setPendingInvite({ organization_name: 'Acme Corp' })
        logic.actions.resendPendingInvite('alice@acme.com')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInviteResent).toBe(true)
        expect(logic.values.isPendingInviteResending).toBe(false)
    })

    it('clears the resent state when a new invite banner is shown', async () => {
        logic.actions.setPendingInvite({ organization_name: 'Acme Corp' })
        logic.actions.setPendingInviteResent(true)
        logic.actions.setPendingInvite({ organization_name: 'Other Corp' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInviteResent).toBe(false)
    })
})

describe('signupLogic — retrying a panel after a failed submit', () => {
    let logic: ReturnType<typeof signupLogic.build>
    let signupRequestCount: number

    const advanceToOnboardingPanel = async (): Promise<void> => {
        logic.actions.precheckSignupEmail('free@example.com')
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSignupPanelAuthValue('password', 'Str0ng-Test-Pass!')
        logic.actions.submitSignupPanelAuth()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.panel).toBe(2)
    }

    beforeEach(() => {
        signupRequestCount = 0
        useMocks({
            post: {
                '/api/signup/precheck': async (info) => {
                    const { email } = (await info.request.clone().json()) as { email: string }
                    return email === 'taken@example.com'
                        ? [
                              409,
                              {
                                  type: 'validation_error',
                                  code: 'account_exists',
                                  detail: 'There is already an account with this email address.',
                              },
                          ]
                        : [200, { email_exists: false, pending_invite: null }]
                },
                '/api/signup/': () => {
                    signupRequestCount++
                    return [400, { type: 'validation_error', code: 'error', detail: 'Mocked failure', attr: null }]
                },
            },
        })
        initKeaTests()
        router.actions.push('/signup')
        logic = signupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('advances when a different email is submitted after an account-exists error', async () => {
        logic.actions.precheckSignupEmail('taken@example.com')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.panel).toBe(0)
        expect(logic.values.signupEmailError).toBe('There is already an account with this email address.')

        logic.actions.precheckSignupEmail('free@example.com')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.panel).toBe(1)
        expect(logic.values.signupEmailError).toBeNull()
    })

    it('reissues the signup request when onboarding is submitted again after a generic error', async () => {
        await advanceToOnboardingPanel()
        logic.actions.setSignupPanelOnboardingValues({
            name: 'John Smith',
            organization_name: 'Hogflix',
            role_at_organization: 'engineer',
            referral_source: '',
            referral_source_ai_prompt: '',
        })
        logic.actions.submitSignupPanelOnboarding()
        await expectLogic(logic).toFinishAllListeners()
        expect(signupRequestCount).toBe(1)
        expect(logic.values.signupPanelOnboardingManualErrors.generic).not.toBeUndefined()

        logic.actions.submitSignupPanelOnboarding()
        await expectLogic(logic).toFinishAllListeners()

        expect(signupRequestCount).toBe(2)
    })
})

describe('signupLogic — name handling', () => {
    let logic: ReturnType<typeof signupLogic.build>
    let signupRequestBody: Record<string, any> | null

    const advanceToOnboardingPanel = async (): Promise<void> => {
        logic.actions.precheckSignupEmail('test@example.com')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.panel).toBe(1)
        logic.actions.setSignupPanelAuthValue('password', 'Str0ng-Test-Pass!')
        logic.actions.submitSignupPanelAuth()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.panel).toBe(2)
    }

    beforeEach(() => {
        signupRequestBody = null
        useMocks({
            post: {
                '/api/signup/precheck': () => [200, { email_exists: false, pending_invite: null }],
                // 400 rather than 201 so that the submit handler never assigns `location.href`,
                // which jsdom does not implement. The request body is captured before the response.
                '/api/signup/': async (info) => {
                    signupRequestBody = (await info.request.clone().json()) as Record<string, any>
                    return [400, { type: 'validation_error', code: 'error', detail: 'Mocked failure', attr: null }]
                },
            },
        })
        initKeaTests()
        router.actions.push('/signup')
        logic = signupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('trims and splits the name before building the signup payload', async () => {
        await advanceToOnboardingPanel()
        logic.actions.setSignupPanelOnboardingValues({
            name: '  John van Der Berg ',
            organization_name: 'Hogflix',
            role_at_organization: 'engineer',
            referral_source: '',
            referral_source_ai_prompt: '',
        })
        logic.actions.submitSignupPanelOnboarding()
        await expectLogic(logic).toFinishAllListeners()

        expect(signupRequestBody?.first_name).toBe('John')
        expect(signupRequestBody?.last_name).toBe('van Der Berg')
    })

    it('sends only the follow-up answer whose question is shown for the referral source', async () => {
        await advanceToOnboardingPanel()
        logic.actions.setSignupPanelOnboardingValues({
            name: 'John Smith',
            organization_name: 'Hogflix',
            role_at_organization: 'engineer',
            referral_source: 'A YouTube video',
            // A stale answer from before the referral source was edited away from an AI mention
            referral_source_ai_prompt: 'best analytics tool',
            referral_source_influencer: 'The Hedgehog Dev channel',
        })
        logic.actions.submitSignupPanelOnboarding()
        await expectLogic(logic).toFinishAllListeners()

        expect(signupRequestBody?.referral_source).toBe('A YouTube video')
        expect(signupRequestBody?.referral_source_ai_prompt).toBe('')
        expect(signupRequestBody?.referral_source_influencer).toBe('The Hedgehog Dev channel')
    })

    it('omits a whitespace-only organization name so the backend applies its default', async () => {
        await advanceToOnboardingPanel()
        logic.actions.setSignupPanelOnboardingValues({
            name: 'John Smith',
            organization_name: '   ',
            role_at_organization: 'engineer',
            referral_source: '',
            referral_source_ai_prompt: '',
        })
        logic.actions.submitSignupPanelOnboarding()
        await expectLogic(logic).toFinishAllListeners()

        expect(signupRequestBody).not.toBeNull()
        expect(signupRequestBody).not.toHaveProperty('organization_name')
    })

    it('fails client-side validation for a whitespace-only name without issuing the POST', async () => {
        await advanceToOnboardingPanel()
        logic.actions.setSignupPanelOnboardingValues({
            name: '   ',
            organization_name: 'Hogflix',
            role_at_organization: 'engineer',
            referral_source: '',
            referral_source_ai_prompt: '',
        })
        logic.actions.submitSignupPanelOnboarding()
        await expectLogic(logic).toFinishAllListeners()

        expect(signupRequestBody).toBeNull()
        expect(logic.values.panel).toBe(2)
    })

    it('surfaces a first_name API error on the name field instead of the generic banner', async () => {
        useMocks({
            post: {
                '/api/signup/': () => [
                    400,
                    {
                        type: 'validation_error',
                        code: 'blank',
                        detail: 'This field may not be blank.',
                        attr: 'first_name',
                    },
                ],
            },
        })
        await advanceToOnboardingPanel()
        logic.actions.setSignupPanelOnboardingValues({
            name: 'John Smith',
            organization_name: 'Hogflix',
            role_at_organization: 'engineer',
            referral_source: '',
            referral_source_ai_prompt: '',
        })
        logic.actions.submitSignupPanelOnboarding()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.signupPanelOnboardingManualErrors.name).toBe('This field may not be blank.')
        expect(logic.values.signupPanelOnboardingManualErrors.generic).toBeUndefined()
        // The display-level selector fields read from — the error must remain visible after the
        // failed submit (a successful submit resets showErrors and would hide it)
        expect(logic.values.signupPanelOnboardingErrors.name).toBe('This field may not be blank.')
        expect(logic.values.panel).toBe(2)
    })

    it('sends a password API error back to the password step and lets the next submit through', async () => {
        useMocks({
            post: {
                '/api/signup/': () => [
                    400,
                    {
                        type: 'validation_error',
                        code: 'password_too_weak',
                        detail: 'Add another word or two. Uncommon words are better.',
                        attr: 'password',
                    },
                ],
            },
        })
        await advanceToOnboardingPanel()
        logic.actions.setSignupPanelOnboardingValues({
            name: 'John Smith',
            organization_name: 'Hogflix',
            role_at_organization: 'engineer',
            referral_source: '',
            referral_source_ai_prompt: '',
        })
        logic.actions.submitSignupPanelOnboarding()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.panel).toBe(1)
        expect(logic.values.signupPanelAuthManualErrors.password).toBe(
            'Add another word or two. Uncommon words are better.'
        )
        expect(logic.values.signupPanelOnboardingManualErrors.generic).toBeUndefined()

        logic.actions.setSignupPanelAuthValue('password', 'An0ther-Str0ng-Pass!')
        logic.actions.submitSignupPanelAuth()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.panel).toBe(2)
        expect(logic.values.signupPanelAuthManualErrors.password).toBeUndefined()
    })

    it('drops a stale password error when a different email is submitted', async () => {
        useMocks({
            post: {
                '/api/signup/': () => [
                    400,
                    {
                        type: 'validation_error',
                        code: 'password_too_weak',
                        detail: 'Add another word or two. Uncommon words are better.',
                        attr: 'password',
                    },
                ],
            },
        })
        await advanceToOnboardingPanel()
        logic.actions.setSignupPanelOnboardingValues({
            name: 'John Smith',
            organization_name: 'Hogflix',
            role_at_organization: 'engineer',
            referral_source: '',
            referral_source_ai_prompt: '',
        })
        logic.actions.submitSignupPanelOnboarding()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.signupPanelAuthManualErrors.password).toBeTruthy()

        logic.actions.setPanel(0)
        logic.actions.precheckSignupEmail('other@example.com')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.panel).toBe(1)
        expect(logic.values.signupPanelAuthManualErrors.password).toBeUndefined()
    })
})

describe('signupLogic - pending OAuth connection', () => {
    afterEach(() => {
        setPendingOAuthConnectionCookie(null)
    })

    it.each([
        ['prefills the referral source with the client name', 'Claude', 'Claude'],
        ['leaves the referral source empty without a connection', null, ''],
    ])('%s', async (_name, clientName, expected) => {
        setPendingOAuthConnectionCookie(clientName ? { client_name: clientName, client_id: 'client' } : null)
        initKeaTests()
        router.actions.push('/signup')
        const logic = signupLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            signupPanelOnboarding: expect.objectContaining({ referral_source: expected }),
        })
        logic.unmount()
    })
})
