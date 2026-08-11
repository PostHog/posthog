import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { hedgehogModeLogic } from './hedgehogModeLogic'

describe('hedgehogModeLogic', () => {
    let logic: ReturnType<typeof hedgehogModeLogic.build>

    beforeEach(() => {
        useMocks({
            patch: {
                // The remote save must not gate quitting - reject it to prove the widget still closes.
                '/api/users/@me/hedgehog_config': () => [500, {}],
            },
        })
        // Start with hedgehog mode already on, as a returning user would.
        window.POSTHOG_APP_CONTEXT = {
            current_user: { ...MOCK_DEFAULT_USER, hedgehog_config: { version: 2, enabled: true } },
        } as unknown as AppContext
        initKeaTests()
        logic = hedgehogModeLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('disables the widget at once, even when the remote config save fails', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadRemoteConfigSuccess'])
            .toMatchValues({ hedgehogModeEnabled: true })

        await expectLogic(logic, () => {
            logic.actions.setHedgehogModeEnabled(false)
        }).toMatchValues({ hedgehogModeEnabled: false })

        await expectLogic(logic)
            .toDispatchActions(['setRemoteConfigUpdateDisabled'])
            .toMatchValues({ hedgehogModeEnabled: false, remoteConfigUpdateDisabled: true })
    })
})
