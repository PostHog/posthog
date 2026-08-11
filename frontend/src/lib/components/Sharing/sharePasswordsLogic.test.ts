import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sharePasswordsLogic } from './sharePasswordsLogic'

const dashboardId = 123

describe('sharePasswordsLogic', () => {
    let logic: ReturnType<typeof sharePasswordsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
        jest.spyOn(lemonToast, 'info').mockImplementation(jest.fn())
        jest.spyOn(lemonToast, 'success').mockImplementation(jest.fn())
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('surfaces an error toast when the server refuses the delete', async () => {
        // Guards the missing `return` in api.sharing.deletePassword: without the returned promise
        // the rejection never reaches the listener and a failed delete reports success.
        useMocks({
            get: { '/api/environments/:team_id/dashboards/:dashboard_id/sharing/': { share_passwords: [] } },
            delete: {
                '/api/environments/:team_id/dashboards/:dashboard_id/sharing/passwords/:password_id/': () => [
                    500,
                    { detail: 'Server error' },
                ],
            },
        })

        logic = sharePasswordsLogic({ dashboardId })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.deletePassword('pw-1')
        }).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalledWith('Server error')
        expect(lemonToast.success).not.toHaveBeenCalled()
    })

    it('reconciles a 404 delete by reloading and telling the user the password was already gone', async () => {
        useMocks({
            get: { '/api/environments/:team_id/dashboards/:dashboard_id/sharing/': { share_passwords: [] } },
            delete: {
                '/api/environments/:team_id/dashboards/:dashboard_id/sharing/passwords/:password_id/': () => [
                    404,
                    { detail: 'Password not found' },
                ],
            },
        })

        logic = sharePasswordsLogic({ dashboardId })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.deletePassword('pw-1')
        })
            .toDispatchActions(['deletePassword', 'loadSharePasswords'])
            .toFinishAllListeners()

        expect(lemonToast.info).toHaveBeenCalledWith('Password was already deleted')
        expect(lemonToast.error).not.toHaveBeenCalled()
    })
})
