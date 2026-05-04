import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { signupLogic } from './signupLogic'

describe('signupLogic — pending invite redirect', () => {
    let logic: ReturnType<typeof signupLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/signup/precheck': () => [
                    200,
                    {
                        email_exists: false,
                        pending_invite: {
                            id: 'invite-123',
                            organization_name: 'Acme Corp',
                        },
                    },
                ],
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

    it('redirects to invite signup when pending_invite is returned', async () => {
        logic.actions.setSignupPanelEmailValue('email', 'alice@acme.com')
        logic.actions.submitSignupPanelEmail()
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.location.pathname).toEqual('/signup/invite-123/')
        expect(router.values.searchParams).toEqual(expect.objectContaining({ from_signup_redirect: '1' }))
    })

    it('does not redirect when skip_invite_check is set on the URL', async () => {
        router.actions.push('/signup', { skip_invite_check: '1' })
        logic.actions.setSignupPanelEmailValue('email', 'alice@acme.com')
        logic.actions.submitSignupPanelEmail()
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.location.pathname).toEqual('/signup')
        expect(router.values.searchParams).toEqual({ skip_invite_check: '1' })
    })

    it('does not redirect when pending_invite is null', async () => {
        useMocks({
            post: {
                '/api/signup/precheck': () => [200, { email_exists: false, pending_invite: null }],
            },
        })
        logic.actions.setSignupPanelEmailValue('email', 'stranger@nowhere.com')
        logic.actions.submitSignupPanelEmail()
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.location.pathname).toEqual('/signup')
    })
})
