import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { userLogic } from 'scenes/userLogic'

import { userDetailsLogic } from './userDetailsLogic'

describe('userDetailsLogic', () => {
    let logic: ReturnType<typeof userDetailsLogic.build>

    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
    })

    it('reloads the user on mount and on window focus', async () => {
        // Refetching is what lets the settings tab notice an email change verified in another tab,
        // so mount and focus must each trigger a fresh load of the user.
        logic = userDetailsLogic()
        logic.mount()

        await expectLogic(userLogic).toDispatchActions(['loadUser'])

        await expectLogic(userLogic, () => {
            window.dispatchEvent(new Event('focus'))
        }).toDispatchActions(['loadUser'])
    })
})
