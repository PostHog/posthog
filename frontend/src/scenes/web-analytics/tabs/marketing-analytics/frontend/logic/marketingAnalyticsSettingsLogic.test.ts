import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'

describe('marketing settings partial updates', () => {
    beforeEach(() => initKeaTests())

    it('does not submit goals when changing the test-account filter', async () => {
        const logic = marketingAnalyticsSettingsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.updateFilterTestAccounts(true))
            .toDispatchActions([
                teamLogic.actionCreators.updateCurrentTeam({
                    marketing_analytics_config: { filter_test_accounts: true },
                }),
            ])
            .toFinishAllListeners()
        logic.unmount()
    })
})
