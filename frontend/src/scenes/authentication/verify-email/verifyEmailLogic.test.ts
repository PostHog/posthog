import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { verifyEmailLogic } from './verifyEmailLogic'

describe('verifyEmailLogic', () => {
    let logic: ReturnType<typeof verifyEmailLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = verifyEmailLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    // Guards the dead end: an already-verified user requesting a fresh link used to fall through
    // to the generic failure toast. It must now route them to login instead.
    it('redirects an already-verified user to login when a new link is refused', async () => {
        jest.spyOn(api, 'create').mockRejectedValue({ code: 'already_verified' })

        await expectLogic(logic, () => {
            logic.actions.requestVerificationLink('some-uuid')
        }).toFinishAllListeners()

        expect(router.values.location.pathname).toEqual('/login')
    })
})
