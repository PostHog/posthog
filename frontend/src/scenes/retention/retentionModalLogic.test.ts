import { expectLogic } from 'kea-test-utils'

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
            name: 'resolves the breakdown row sharing the selected row label',
            rows: [
                cohortRow('Day 0', 100, 'Chrome'),
                cohortRow('Day 1', 90, 'Chrome'),
                cohortRow('Day 0', 50, 'Firefox'),
            ],
            rowIndex: 0,
            breakdownValue: 'Firefox',
            expectedCount: 50,
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

    it('keeps the modal open while the results are empty mid-reload', async () => {
        await loadResults(fourCohorts)
        await expectLogic(logic, () => {
            logic.actions.openModal(3)
        }).toFinishAllListeners()

        await loadResults([])

        expect(logic.values.selectedInterval).toBe(3)
    })
})
