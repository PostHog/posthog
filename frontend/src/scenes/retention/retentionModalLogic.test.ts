import { expectLogic } from 'kea-test-utils'

import { AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE } from 'scenes/insights/filters/aggregationTargetUtils'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, NodeKind, RetentionQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightModel, RetentionPeriod } from '~/types'

import { retentionLogic } from './retentionLogic'
import { retentionModalLogic } from './retentionModalLogic'

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
}

const retentionQuery: RetentionQuery = {
    kind: NodeKind.RetentionQuery,
    retentionFilter: {
        period: RetentionPeriod.Day,
        targetEntity: { id: '$pageview', type: 'events' },
        returningEntity: { id: '$pageview', type: 'events' },
    },
}

const dataWarehouseEntity = {
    id: 'warehouse_orders',
    type: 'data_warehouse' as const,
    table_name: 'warehouse_orders',
    timestamp_field: 'created_at',
    aggregation_target_field: 'order_id',
}

const dataWarehouseQuery: RetentionQuery = {
    kind: NodeKind.RetentionQuery,
    retentionFilter: {
        period: RetentionPeriod.Day,
        targetEntity: dataWarehouseEntity,
        returningEntity: dataWarehouseEntity,
        customAggregationTarget: true,
    },
}

const cohortRow = (
    label: string,
    count: number,
    breakdownValue?: string
): Record<string, string | number | Record<string, number>[]> => ({
    date: '2024-01-01T00:00:00Z',
    label,
    values: [{ count }, { count }],
    ...(breakdownValue !== undefined ? { breakdown_value: breakdownValue } : {}),
})

const fourCohorts = [cohortRow('Day 0', 100), cohortRow('Day 1', 90), cohortRow('Day 2', 80), cohortRow('Day 3', 70)]

// Two breakdown groups, each with the same interval labels, as the query runner emits them
const twoBreakdownGroups = [
    cohortRow('Day 0', 100, 'Chrome'),
    cohortRow('Day 1', 90, 'Chrome'),
    cohortRow('Day 0', 50, 'Firefox'),
    cohortRow('Day 1', 40, 'Firefox'),
]

let logic: ReturnType<typeof retentionModalLogic.build>

describe('retentionModalLogic', () => {
    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/cohorts/': { count: 0, results: [] },
                '/api/environments/:team_id/data_color_themes/': [],
            },
            post: {
                '/api/environments/:team_id/query/': { results: [], columns: [] },
            },
        })
        initKeaTests(false)
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()

        dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode }).mount()

        logic = retentionModalLogic(insightProps)
        logic.mount()
    })

    async function loadResults(result: Record<string, any>[]): Promise<void> {
        await expectLogic(logic, () => {
            retentionLogic(insightProps).actions.updateQuerySource(retentionQuery)
            // Rebuilding with the query as props mirrors how InsightViz passes the source query
            // down; retentionLogic.results gates on it. cachedResults set the response without
            // a network round-trip.
            dataNodeLogic({
                key: 'InsightViz.new',
                query: retentionQuery as DataNode,
                cachedResults: { result } as Partial<InsightModel>,
            })
        }).toFinishAllListeners()
    }

    it.each([
        {
            name: 'resolves the row at the selected index',
            rows: fourCohorts,
            rowIndex: 1,
            breakdownValue: undefined,
            expectedCount: 90,
        },
        {
            name: 'resolves null when the selected index is past the end of the results',
            rows: [cohortRow('Day 0', 100), cohortRow('Day 1', 90)],
            rowIndex: 3,
            breakdownValue: undefined,
            expectedCount: null,
        },
        {
            name: 'resolves null when the results are empty',
            rows: [],
            rowIndex: 0,
            breakdownValue: undefined,
            expectedCount: null,
        },
        {
            name: 'resolves the row at the selected index within the breakdown group',
            rows: twoBreakdownGroups,
            rowIndex: 1,
            breakdownValue: 'Firefox',
            expectedCount: 40,
        },
        {
            name: 'resolves null when the index is past the end of the breakdown group',
            rows: twoBreakdownGroups,
            rowIndex: 3,
            breakdownValue: 'Firefox',
            expectedCount: null,
        },
        {
            name: 'resolves null when the selected breakdown value is absent',
            rows: twoBreakdownGroups,
            rowIndex: 0,
            breakdownValue: 'Safari',
            expectedCount: null,
        },
    ])('$name', async ({ rows, rowIndex, breakdownValue, expectedCount }) => {
        await loadResults(rows)

        await expectLogic(logic, () => {
            logic.actions.openModal(rowIndex, breakdownValue)
        }).toFinishAllListeners()

        if (expectedCount === null) {
            expect(logic.values.selectedRow).toBeNull()
        } else {
            expect(logic.values.selectedRow?.values[0].count).toBe(expectedCount)
        }
    })

    it('closes the modal when the reloaded results no longer contain the selected row', async () => {
        await loadResults(fourCohorts)
        await expectLogic(logic, () => {
            logic.actions.openModal(3)
        }).toFinishAllListeners()
        expect(logic.values.selectedRow?.values[0].count).toBe(70)

        await loadResults([cohortRow('Day 0', 100), cohortRow('Day 1', 90)])

        expect(logic.values.selectedInterval).toBeNull()
        expect(logic.values.selectedRow).toBeNull()
    })

    it('keeps the modal open when the reloaded results still contain the selected row', async () => {
        await loadResults(fourCohorts)
        await expectLogic(logic, () => {
            logic.actions.openModal(1)
        }).toFinishAllListeners()

        await loadResults([cohortRow('Day 0', 10), cohortRow('Day 1', 9), cohortRow('Day 2', 8)])

        expect(logic.values.selectedInterval).toBe(1)
        expect(logic.values.selectedRow?.values[0].count).toBe(9)
    })

    it('closes the modal when the results come back empty', async () => {
        await loadResults(fourCohorts)
        await expectLogic(logic, () => {
            logic.actions.openModal(3)
        }).toFinishAllListeners()

        await loadResults([])

        expect(logic.values.selectedInterval).toBeNull()
        expect(logic.values.selectedRow).toBeNull()
    })

    it('closes the modal when the selected breakdown value disappears', async () => {
        await loadResults(twoBreakdownGroups)
        await expectLogic(logic, () => {
            logic.actions.openModal(1, 'Firefox')
        }).toFinishAllListeners()
        expect(logic.values.selectedRow?.values[0].count).toBe(40)

        await loadResults([cohortRow('Day 0', 100, 'Chrome'), cohortRow('Day 1', 90, 'Chrome')])

        expect(logic.values.selectedInterval).toBeNull()
        expect(logic.values.selectedRow).toBeNull()
    })

    it('disables the person modal and relabels actors for a custom aggregation target', async () => {
        await expectLogic(logic, () => {
            retentionLogic(insightProps).actions.updateQuerySource(dataWarehouseQuery)
        }).toMatchValues({
            canOpenPersonModal: false,
            aggregationTargetLabel: AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE,
        })

        // Backstop: even when a render surface dispatches openModal anyway, no actors query fires
        await expectLogic(logic, () => {
            logic.actions.openModal(0)
        }).toNotHaveDispatchedActions(['loadPeople'])

        await expectLogic(logic, () => {
            retentionLogic(insightProps).actions.updateQuerySource(retentionQuery)
        }).toMatchValues({
            canOpenPersonModal: true,
        })

        await expectLogic(logic, () => {
            logic.actions.openModal(0)
        }).toDispatchActions(['loadPeople'])
    })

    it('closes an open modal when the aggregation target becomes custom', async () => {
        await loadResults(fourCohorts)
        await expectLogic(logic, () => {
            logic.actions.openModal(1)
        }).toFinishAllListeners()
        expect(logic.values.selectedRow?.values[0].count).toBe(90)

        await expectLogic(logic, () => {
            retentionLogic(insightProps).actions.updateQuerySource(dataWarehouseQuery)
        }).toFinishAllListeners()

        // Cleared, not just hidden: switching back must not restore the old cohort
        expect(logic.values.selectedInterval).toBeNull()
        expect(logic.values.selectedRow).toBeNull()
    })
})
