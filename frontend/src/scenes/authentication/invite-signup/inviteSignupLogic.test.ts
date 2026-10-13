import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inviteSignupLogic } from './inviteSignupLogic'

const INVITE_ID = '1234'

describe('inviteSignupLogic', () => {
    let logic: ReturnType<typeof inviteSignupLogic.build>

    beforeEach(async () => {
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

    it('submits without a role, and sends the next attempt after the API rejects one', async () => {
        const signupRequest = jest.fn(() => [400, { code: 'invalid_input', detail: 'Something went wrong.' }])
        useMocks({ post: { [`/api/signup/${INVITE_ID}/`]: signupRequest } })
        logic.actions.setSignupValues({ first_name: 'Jane', password: 'a-long-and-unusual-passphrase-42' })

        await expectLogic(logic, () => {
            logic.actions.submitSignup()
        }).toFinishAllListeners()
        expect(logic.values.signupManualErrors).toEqual({
            generic: { code: 'invalid_input', detail: 'Something went wrong.' },
        })

        // Nothing touches `generic`, so without preSubmit clearing it every retry would fail validation
        await expectLogic(logic, () => {
            logic.actions.submitSignup()
        }).toFinishAllListeners()
        expect(signupRequest).toHaveBeenCalledTimes(2)
    })
})
