import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyMathType } from '~/types'

import { marketingAttributionLogic } from './marketingAttributionLogic'

it('restricts revenue queries to valid goals and drops a selection from the previous project', async () => {
    initKeaTests()
    const logic = marketingAttributionLogic()
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
    const revenue: ConversionGoalFilter = {
        kind: NodeKind.EventsNode,
        event: 'purchase',
        conversion_goal_id: 'revenue',
        conversion_goal_name: 'Purchases',
        schema_map: {},
        math: PropertyMathType.Sum,
        math_property: 'amount',
        counts_as_revenue: true,
    }
    const loadGoals = async (id: number, goals: ConversionGoalFilter[]): Promise<void> => {
        await expectLogic(logic, () =>
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                id,
                marketing_analytics_config: { conversion_goals: goals },
            })
        ).toFinishAllListeners()
    }
    await loadGoals(101, [
        { ...revenue, conversion_goal_id: 'unmarked', counts_as_revenue: false },
        { ...revenue, conversion_goal_id: 'missing-amount', math_property: undefined },
        {
            ...revenue,
            conversion_goal_id: 'warehouse',
            kind: NodeKind.DataWarehouseNode,
            id: 'orders',
            table_name: 'orders',
            id_field: 'id',
            timestamp_field: 'timestamp',
            distinct_id_field: 'distinct_id',
        },
        revenue,
    ])
    expect(logic.values.revenueGoals).toEqual([revenue])
    logic.actions.setRevenueGoalId('revenue')
    logic.actions.setAllowMultipleConversionsPerVisitor(false)
    expect(logic.values.revenueQuery).toMatchObject({
        conversionGoalId: 'revenue',
        allowMultipleConversionsPerVisitor: true,
    })
    await loadGoals(102, [{ ...revenue, conversion_goal_id: 'other-project' }])
    expect(logic.values.revenueQuery?.conversionGoalId).toBe('other-project')
    await loadGoals(103, [])
    expect(logic.values.revenueQuery).toBeNull()
    logic.unmount()
})
