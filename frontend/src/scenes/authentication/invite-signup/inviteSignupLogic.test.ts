import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inviteSignupLogic } from './inviteSignupLogic'

const INVITE_ID = 'abc123'

const mocks = (submitStatus: number): Parameters<typeof useMocks>[0] => ({
    get: {
        [`/api/signup/${INVITE_ID}/`]: () => [
            200,
            { id: INVITE_ID, target_email: 'joiner@example.com', organization_name: 'Acme Corp' },
        ],
    },
    post: {
        [`/api/signup/${INVITE_ID}/`]: () => [submitStatus, {}],
        // A 200 (no throw) means the email has no account yet.
        '/api/signup/precheck': () => [200, { email_exists: false, pending_invite: null }],
    },
})

describe('inviteSignupLogic — transient submit failure', () => {
    let logic: ReturnType<typeof inviteSignupLogic.build>

    const mountAndFill = async (): Promise<void> => {
        initKeaTests()
        router.actions.push(`/signup/${INVITE_ID}`)
        logic = inviteSignupLogic()
        logic.mount()
        logic.actions.prevalidateInvite(INVITE_ID)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setSignupValues({
            password: 'Str0ng-Test-Pass!',
            first_name: 'Jane Doe',
            role_at_organization: 'engineer',
        })
    }

    afterEach(() => {
        logic.unmount()
    })

    it('shows a retryable error when a 5xx submit created no account', async () => {
        useMocks(mocks(503))
        await mountAndFill()
        logic.actions.submitSignup()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.signupManualErrors.generic.retryable).toBe(true)
        expect(logic.values.signupManualErrors.generic.detail).toContain('try again')
    })

    it('surfaces the plain error for a 4xx submit', async () => {
        useMocks(mocks(400))
        await mountAndFill()
        logic.actions.submitSignup()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.signupManualErrors.generic.retryable).toBeUndefined()
    })
})
