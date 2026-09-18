import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'

jest.mock('posthog-js')

describe('marketing settings project changes', () => {
    beforeEach(() => {
        jest.mocked(posthog.capture).mockClear()
        initKeaTests()
    })

    it('reports manual goal saves with the surface they came from', async () => {
        const logic = marketingAnalyticsSettingsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const goal: ConversionGoalFilter = {
            kind: NodeKind.EventsNode,
            event: 'purchase',
            conversion_goal_id: 'purchases',
            conversion_goal_name: 'Purchases',
            schema_map: {},
        }

        await expectLogic(logic, () => logic.actions.addOrUpdateConversionGoal(goal)).toFinishAllListeners()
        expect(posthog.capture).toHaveBeenCalledWith('marketing analytics settings updated', {
            field: 'conversion_goals',
            entry_point: 'project_settings',
        })

        logic.actions.setSetupEntryPoint('dashboard_goal_suggestions')
        await expectLogic(logic, () => logic.actions.removeConversionGoal('purchases')).toFinishAllListeners()
        expect(posthog.capture).toHaveBeenCalledWith('marketing analytics settings updated', {
            field: 'conversion_goals',
            entry_point: 'dashboard_goal_suggestions',
        })
        logic.unmount()
    })

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
