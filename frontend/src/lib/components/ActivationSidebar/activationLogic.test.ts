import { expectLogic } from 'kea-test-utils'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { membersLogic } from 'scenes/organization/Settings/membersLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { initKeaTests } from '~/test/init'
import { activationLogic } from './activationLogic'

describe('activationLogic', () => {
    let logic: ReturnType<typeof activationLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = activationLogic()
        logic.mount()
        await expectLogic(logic).toMount([inviteLogic, membersLogic, teamLogic, pluginsLogic, navigationLogic])
    })

    afterEach(() => logic.unmount())

    it('should load custom events on mount', async () => {
        expectLogic(logic).toDispatchActions(['loadCustomEvents', 'loadInsights'])
    })

    it('should report activation sidebar shown', async () => {
        navigationLogic.actions.showActivationSideBar()
        expectLogic(logic).toDispatchActions(['reportActivationSidebarShown'])
    })
})
