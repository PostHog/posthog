import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { twoFactorLogic } from './twoFactorLogic'

describe('twoFactorLogic', () => {
    it('never keeps generated backup codes hidden behind a closed modal', async () => {
        let respond: () => void = () => {}
        const responded = new Promise<void>((resolve) => (respond = resolve))
        useMocks({
            post: {
                '/api/users/@me/two_factor_backup_codes/': async () => {
                    await responded
                    return [200, { backup_codes: ['c0ffee01'] }]
                },
            },
        })
        initKeaTests()
        const logic = twoFactorLogic()
        logic.mount()

        logic.actions.toggleBackupCodesModal(true)
        logic.actions.generateBackupCodes()
        logic.actions.toggleBackupCodesModal(false)
        respond()
        await expectLogic(logic).toDispatchActions(['generateBackupCodesSuccess'])

        expect(logic.values).toMatchObject({
            isBackupCodesModalOpen: true,
            generatingCodes: { backup_codes: ['c0ffee01'] },
        })
        logic.actions.toggleBackupCodesModal(false)
        expect(logic.values.generatingCodes).toBeNull()
    })
})
