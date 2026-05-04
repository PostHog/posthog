import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { signupLogic } from './signupLogic'

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
        logic.actions.setSignupPanelEmailValue('email', 'alice@acme.com')
        logic.actions.submitSignupPanelEmail()
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
        logic.actions.setSignupPanelEmailValue('email', 'stranger@nowhere.com')
        logic.actions.submitSignupPanelEmail()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInvite).toBeNull()
        expect(logic.values.panel).toBe(1)
    })

    it('advances the panel when the user dismisses the banner', async () => {
        logic.actions.setSignupPanelEmailValue('email', 'alice@acme.com')
        logic.actions.submitSignupPanelEmail()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInvite).not.toBeNull()
        logic.actions.dismissPendingInvite()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.pendingInvite).toBeNull()
        expect(logic.values.panel).toBe(1)
    })

    it('skips the banner when skip_invite_check=1 is on the URL', async () => {
        router.actions.push('/signup', { skip_invite_check: '1' })
        logic.actions.setSignupPanelEmailValue('email', 'alice@acme.com')
        logic.actions.submitSignupPanelEmail()
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
