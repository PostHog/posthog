import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { userDangerZoneLogic } from './userDangerZoneLogic'

const PENDING_ORGANIZATION = { ...MOCK_DEFAULT_USER.organizations![0]!, is_pending_deletion: true }

describe('userDangerZoneLogic', () => {
    let logic: ReturnType<typeof userDangerZoneLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, organizations: [PENDING_ORGANIZATION] }],
            },
        })
        initKeaTests()
        userLogic.mount()
        logic = userDangerZoneLogic()
        logic.mount()
    })

    it('keeps an organization pending deletion in the list and blocks account deletion', async () => {
        logic.actions.setOrganizationToDelete(PENDING_ORGANIZATION)
        logic.actions.setIsUserDeletionConfirmed(true)
        logic.actions.setDeleteUserModalOpen(true)
        logic.actions.deleteOrganizationSuccess({ redirectPath: urls.settings('user-danger-zone') })

        await expectLogic(userLogic).toDispatchActions(['loadUser', 'loadUserSuccess'])

        expectLogic(logic).toMatchValues({
            blockingOrganizations: [PENDING_ORGANIZATION],
            hasPendingOrganizationDeletion: true,
            deleteAccountDisabledReason:
                'Wait for your organization deletion to finish. This usually takes a few minutes.',
        })

        logic.actions.setDeleteUserModalOpen(false)
    })
})
