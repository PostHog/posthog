import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'

describe('marketing settings project changes', () => {
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

    it('replaces prior-project goals and clears them for an unconfigured project', async () => {
        const logic = marketingAnalyticsSettingsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const goal = (id: string): ConversionGoalFilter => ({
            kind: NodeKind.EventsNode,
            event: 'purchase',
            conversion_goal_id: id,
            conversion_goal_name: 'Purchases',
            schema_map: {},
        })
        for (const [id, goals] of [
            [101, [goal('first')]],
            [102, [goal('second')]],
            [103, []],
        ] as const) {
            await expectLogic(logic, () =>
                teamLogic.actions.loadCurrentTeamSuccess({
                    ...teamLogic.values.currentTeam!,
                    id,
                    marketing_analytics_config: { conversion_goals: [...goals] },
                } as TeamType)
            ).toFinishAllListeners()
            expect(logic.values.conversion_goals).toEqual(goals)
            expect(logic.values.savedMarketingAnalyticsConfig.conversion_goals).toEqual(goals)
        }
        logic.unmount()
    })
})
