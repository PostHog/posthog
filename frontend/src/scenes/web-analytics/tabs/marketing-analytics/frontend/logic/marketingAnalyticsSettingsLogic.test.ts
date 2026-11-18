import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { TeamType } from '~/types'

import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'

jest.mock('posthog-js')

describe('marketing settings project changes', () => {
    beforeEach(() => {
        jest.mocked(posthog.capture).mockClear()
        useMocks({
            patch: {
                '/api/environments/:team_id': async ({ request }) => [
                    200,
                    { ...teamLogic.values.currentTeam, ...((await request.json()) as Partial<TeamType>) },
                ],
            },
        })
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

        logic.actions.setSetupEntryPoint('dashboard_goal_suggestions')
        await expectLogic(logic, () => logic.actions.addOrUpdateConversionGoal(goal)).toFinishAllListeners()
        expect(posthog.capture).toHaveBeenCalledWith('marketing analytics settings updated', {
            field: 'conversion_goals',
            entry_point: 'project_settings',
        })

        await expectLogic(router, () => router.actions.push(urls.marketingAnalyticsApp())).toFinishAllListeners()
        logic.actions.setSetupEntryPoint(null)
        await expectLogic(logic, () => logic.actions.updateAttributionWindowDays(14)).toFinishAllListeners()
        expect(posthog.capture).toHaveBeenCalledWith('marketing analytics settings updated', {
            field: 'attribution_window_days',
            entry_point: 'direct',
        })
        logic.actions.setSetupEntryPoint('dashboard_goal_suggestions')
        await expectLogic(logic, () => logic.actions.removeConversionGoal('purchases')).toFinishAllListeners()
        expect(posthog.capture).toHaveBeenCalledWith('marketing analytics settings updated', {
            field: 'conversion_goals',
            entry_point: 'dashboard_goal_suggestions',
        })
        logic.unmount()
    })

    it.each([200, 500])('reports a pending save only after a successful response (%s)', async (status) => {
        const logic = marketingAnalyticsSettingsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        let completeRequest!: () => void
        const responseReady = new Promise<void>((resolve) => {
            completeRequest = resolve
        })
        useMocks({
            patch: {
                '/api/environments/:team_id': async ({ request }) => {
                    const payload = (await request.json()) as Partial<TeamType>
                    await responseReady
                    return [status, { ...teamLogic.values.currentTeam, ...payload }]
                },
            },
        })
        await expectLogic(router, () => router.actions.push(urls.marketingAnalyticsApp())).toFinishAllListeners()
        logic.actions.setSetupEntryPoint('dashboard_goal_suggestions')
        const save = expectLogic(logic, () => logic.actions.updateAttributionWindowDays(14)).toDispatchActions([
            teamLogic.actionTypes.updateCurrentTeam,
        ])
        await save
        expect(posthog.capture).not.toHaveBeenCalledWith('marketing analytics settings updated', expect.anything())

        logic.actions.setSetupEntryPoint(null)
        router.actions.push(urls.settings('project'))
        completeRequest()
        await expectLogic(teamLogic).toFinishAllListeners()
        const updates = jest
            .mocked(posthog.capture)
            .mock.calls.filter(([event]) => event === 'marketing analytics settings updated')
        expect(updates).toEqual(
            status === 200
                ? [
                      [
                          'marketing analytics settings updated',
                          { field: 'attribution_window_days', entry_point: 'dashboard_goal_suggestions' },
                      ],
                  ]
                : []
        )

        await expectLogic(teamLogic, () =>
            teamLogic.actions.updateCurrentTeam({ name: 'Updated project' })
        ).toFinishAllListeners()
        expect(
            jest
                .mocked(posthog.capture)
                .mock.calls.filter(([event]) => event === 'marketing analytics settings updated')
        ).toEqual(updates)
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
        expect(posthog.capture).not.toHaveBeenCalledWith('marketing analytics settings updated', expect.anything())
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
