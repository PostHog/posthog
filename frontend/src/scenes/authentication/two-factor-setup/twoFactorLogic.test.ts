import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { twoFactorLogic } from './twoFactorLogic'

describe('twoFactorLogic', () => {
    it('loads the 2FA status on first read of status, not on mount', async () => {
        const statusRequest = jest.fn(() => [200, { is_enabled: true, backup_codes_remaining: 3 }])
        useMocks({ get: { '/api/users/@me/two_factor_status/': statusRequest } })
        initKeaTests()
        const logic = twoFactorLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(statusRequest).not.toHaveBeenCalled()

        await expectLogic(logic, () => {
            void logic.values.status
        }).toDispatchActions(['loadStatusSuccess'])

        expect(statusRequest).toHaveBeenCalledTimes(1)
        expect(logic.values.status).toMatchObject({ is_enabled: true, backup_codes_remaining: 3 })
    })

    it('flags a failed status load and clears the flag when a retry succeeds', async () => {
        const statusRequest = jest
            .fn()
            .mockReturnValueOnce([500, {}])
            .mockReturnValue([200, { is_enabled: false, backup_codes_remaining: 0 }])
        useMocks({ get: { '/api/users/@me/two_factor_status/': statusRequest } })
        initKeaTests()
        const logic = twoFactorLogic()
        logic.mount()

        await expectLogic(logic, () => {
            void logic.values.status
        }).toDispatchActions(['loadStatusFailure'])
        expect(logic.values).toMatchObject({ status: null, statusLoadFailed: true })

        await expectLogic(logic, () => {
            logic.actions.loadStatus()
        }).toDispatchActions(['loadStatusSuccess'])
        expect(logic.values.statusLoadFailed).toBe(false)
    })

    it('shows the new backup code count after generating codes without refetching the status', async () => {
        const statusRequest = jest.fn(() => [200, { is_enabled: true, backup_codes_remaining: 1 }])
        useMocks({
            get: { '/api/users/@me/two_factor_status/': statusRequest },
            post: {
                '/api/users/@me/two_factor_backup_codes/': () => [200, { backup_codes: ['c0ffee01', 'c0ffee02'] }],
            },
        })
        initKeaTests()
        const logic = twoFactorLogic()
        logic.mount()
        // Reading the status is what loads it, as the 2FA settings do.
        await expectLogic(logic, () => {
            void logic.values.status
        }).toDispatchActions(['loadStatusSuccess'])

        await expectLogic(logic, () => {
            logic.actions.generateBackupCodes()
        })
            .toDispatchActions(['generateBackupCodesSuccess'])
            .toFinishAllListeners()

        expect(logic.values.status?.backup_codes_remaining).toBe(2)
        expect(statusRequest).toHaveBeenCalledTimes(1)
    })

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
