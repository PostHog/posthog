import { expectLogic } from 'kea-test-utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionLineGraphLogic } from 'scenes/retention/retentionLineGraphLogic'

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
describe.skip('retentionLineGraphLogic', () => {
    let logic: ReturnType<typeof retentionLineGraphLogic.build>

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
            logic = retentionLineGraphLogic(props)
            logic.mount()
        })

        it('returns cohort percentage when retention_reference is total', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({
                    insight: InsightType.RETENTION,
                    period: 'Week',
                    retention_reference: 'total',
                } as RetentionFilterType)
            })
                .toFinishAllListeners()
                .toMatchValues(logic, {
                    trendSeries: expect.arrayContaining([
                        expect.objectContaining({ data: [100, 25, 18.75, 5] }),
                        expect.objectContaining({ data: [100, 25, 10] }),
                        expect.objectContaining({ data: [100, 0] }),
                        expect.objectContaining({ data: [0] }),
                    ]),
                })
        })

        it('handles cohort percentage when retention_reference is previous', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({
                    insight: InsightType.RETENTION,
                    period: 'Week',
                    retention_reference: 'previous',
                } as RetentionFilterType)
            })
                .toFinishAllListeners()
                .toMatchValues(logic, {
                    trendSeries: expect.arrayContaining([
                        expect.objectContaining({ data: [100, 25, 75, 26.666666666666668] }),
                        expect.objectContaining({ data: [100, 25, 40] }),
                        expect.objectContaining({ data: [100, 0] }),
                        expect.objectContaining({ data: [0] }),
                    ]),
                })
        })
    })
})
