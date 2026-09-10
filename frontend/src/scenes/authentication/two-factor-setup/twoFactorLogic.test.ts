import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { twoFactorLogic } from './twoFactorLogic'

describe('twoFactorLogic', () => {
    let logic: ReturnType<typeof twoFactorLogic.build>
    let secretsMinted = 0

    beforeEach(() => {
        secretsMinted = 0
    })

    function statusMocks(hasTotp: boolean): Parameters<typeof useMocks>[0] {
        return {
            get: {
                '/api/users/@me/two_factor_status/': () => [
                    200,
                    { is_enabled: hasTotp, backup_codes: [], method: hasTotp ? 'TOTP' : null, has_totp: hasTotp },
                ],
                '/api/users/@me/two_factor_start_setup/': () => {
                    secretsMinted += 1
                    return [200, { success: true, secret: `secret-${secretsMinted}` }]
                },
            },
        }
    }

    async function mountLogic(): Promise<void> {
        initKeaTests()
        logic = twoFactorLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    // Enrollment replaces the secret behind the QR code, so a user who already has an authenticator
    // must not be sent through it again by a stale 403.
    it('mints no secret for a user who already has an authenticator', async () => {
        useMocks(statusMocks(true))
        await mountLogic()

        logic.actions.openTwoFactorSetupModal(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(secretsMinted).toBe(0)
        await expectLogic(logic).toMatchValues({ startSetup: null })
    })

    it('mints a fresh secret after the modal closes', async () => {
        useMocks(statusMocks(false))
        await mountLogic()

        logic.actions.openTwoFactorSetupModal(true)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.closeTwoFactorSetupModal()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.openTwoFactorSetupModal(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(secretsMinted).toBe(2)
        await expectLogic(logic).toMatchValues({ startSetup: { success: true, secret: 'secret-2' } })
    })
})
