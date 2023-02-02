import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { retentionLogic } from 'scenes/retention/retentionLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId, InsightType, RetentionFilterType, RetentionPeriod } from '~/types'
import { useMocks } from '~/mocks/jest'

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

describe('retentionLogic', () => {
    let logic: ReturnType<typeof retentionLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights/retention/': { result },
            },
        })
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }

        beforeEach(() => {
            initKeaTests()
            logic = retentionLogic(props)
            logic.mount()
        })

        it('setFilters calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ insight: InsightType.RETENTION, period: RetentionPeriod.Week })
            })
                .toDispatchActions([
                    (action) =>
                        action.type === insightLogic(props).actionTypes.setFilters &&
                        action.payload.filters?.period === 'Week',
                ])
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        period: 'Week',
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        period: 'Week',
                    }),
                })
        })

        it('insightLogic.setFilters updates filters', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({
                    insight: InsightType.RETENTION,
                    period: RetentionPeriod.Week,
                } as RetentionFilterType)
            })
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        period: 'Week',
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        period: 'Week',
                    }),
                })
        })
    })
})
