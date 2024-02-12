import { expectLogic } from 'kea-test-utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId, InsightType, RetentionFilterType } from '~/types'

const Insight123 = '123' as InsightShortId
const result = [
    {
        values: [
            { count: 400, people: [] },
            { count: 100, people: [] },
            { count: 75, people: [] },
            { count: 20, people: [] },
        ],
        label: 'Week 0',
        date: '2022-07-24T00:00:00Z',
    },
    {
        values: [
            { count: 200, people: [] },
            { count: 50, people: [] },
            { count: 20, people: [] },
        ],
        label: 'Week 1',
        date: '2022-07-31T00:00:00Z',
    },
    {
        values: [
            { count: 10, people: [] },
            { count: 0, people: [] },
        ],
        label: 'Week 2',
        date: '2022-08-07T00:00:00Z',
    },
    {
        values: [{ count: 0, people: [] }],
        label: 'Week 3',
        date: '2022-08-14T00:00:00Z',
    },
]

// TODO: fix with retention cleanup
describe.skip('retentionTableLogic', () => {
    let logic: ReturnType<typeof retentionTableLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights/': { results: [result] },
                '/api/projects/:team/insights/retention/': { result },
            },
        })
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }

        beforeEach(() => {
            initKeaTests()
            logic = retentionTableLogic(props)
            logic.mount()
        })

        it('calculates max number of intervals in the results', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({
                    insight: InsightType.RETENTION,
                    period: 'Week',
                } as RetentionFilterType)
            })
                .toFinishAllListeners()
                .toMatchValues(logic, {
                    maxIntervalsCount: 4,
                })
        })

        it('calculates the table headers', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({
                    insight: InsightType.RETENTION,
                    period: 'Week',
                } as RetentionFilterType)
            })
                .toFinishAllListeners()
                .toMatchValues(logic, {
                    tableHeaders: ['Cohort', 'Size', 'Week 0', 'Week 1', 'Week 2', 'Week 3'],
                })
        })

        it('calculates the table rows', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({
                    insight: InsightType.RETENTION,
                    period: 'Week',
                } as RetentionFilterType)
            })
                .toFinishAllListeners()
                .toMatchValues(logic, {
                    // 1st: Date, 2nd: Total, Nth - percentage
                    tableRows: [
                        [
                            'Jul 24',
                            400,
                            {
                                count: 400,
                                percentage: 100,
                            },
                            {
                                count: 100,
                                percentage: 25,
                            },
                            {
                                count: 75,
                                percentage: 18.75,
                            },
                            {
                                count: 20,
                                percentage: 5,
                            },
                        ],
                        [
                            'Jul 31',
                            200,
                            {
                                count: 200,
                                percentage: 100,
                            },
                            {
                                count: 50,
                                percentage: 25,
                            },
                            {
                                count: 20,
                                percentage: 10,
                            },
                        ],
                        [
                            'Aug 7',
                            10,
                            {
                                count: 10,
                                percentage: 100,
                            },
                            {
                                count: 0,
                                percentage: 0,
                            },
                        ],
                        [
                            'Aug 14',
                            0,
                            {
                                count: 0,
                                percentage: 0,
                            },
                        ],
                    ],
                })
        })
    })
})
