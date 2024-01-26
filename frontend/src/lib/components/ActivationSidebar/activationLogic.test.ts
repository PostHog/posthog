import { expectLogic } from 'kea-test-utils'
import { membersV2Logic } from 'scenes/organization/membersV2Logic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { activationLogic } from './activationLogic'

describe('activationLogic', () => {
    let logic: ReturnType<typeof activationLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = activationLogic()
        logic.mount()
        await expectLogic(logic).toMount([inviteLogic, membersV2Logic, teamLogic, pluginsLogic])
    })

    afterEach(() => logic.unmount())

    it('should load custom events on mount', async () => {
        expectLogic(logic).toDispatchActions(['loadCustomEvents', 'loadInsights'])
    })
})
