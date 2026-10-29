import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { roleAccessControlLogic } from './roleAccessControlLogic'

describe('roleAccessControlLogic', () => {
    let logic: ReturnType<typeof roleAccessControlLogic.build>

    beforeEach(() => {
        initKeaTests()
        router.actions.push(urls.settings('organization-roles'), {}, { role: 'role-a' })
        logic = roleAccessControlLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('syncs the selected role with the role in the URL hash', async () => {
        await expectLogic(logic).toMatchValues({ selectedRoleId: 'role-a' })

        router.actions.push(urls.settings('organization-roles'), {}, { role: 'role-b' })
        await expectLogic(logic).toMatchValues({ selectedRoleId: 'role-b' })

        router.actions.push(urls.settings('organization-roles'))
        await expectLogic(logic).toMatchValues({ selectedRoleId: null })
    })
})
