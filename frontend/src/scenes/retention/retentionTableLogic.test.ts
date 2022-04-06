import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId, InsightType } from '~/types'
import { useMocks } from '~/mocks/jest'

const Insight123 = '123' as InsightShortId
const result = [
    {
        values: [
            { count: 200, people: [] },
            { count: 100, people: [] },
            { count: 75, people: [] },
        ],
        label: 'Chrome::96',
    },
    {
        values: [
            { count: 400, people: [] },
            { count: 200, people: [] },
            { count: 150, people: [] },
        ],
        label: 'Safari::34',
    },
]

describe('retentionTableLogic', () => {
    let logic: ReturnType<typeof retentionTableLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights/': { results: [result] },
                '/api/projects/:team/insights/retention/': { result },
            },
            post: {
                '/api/projects/:team/insights/': { results: [result] },
                '/api/projects/:team/insights/:id/viewed': [201],
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

        it('setFilters calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ insight: InsightType.RETENTION, period: 'Week' })
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
                insightLogic(props).actions.setFilters({ insight: InsightType.RETENTION, period: 'Week' })
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

        it('handles conversion from cohort percentage to derivative of percentages when retentionReference is previous', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({ insight: InsightType.RETENTION, period: 'Week' })
                logic.actions.setRetentionReference('previous')
            })
                .toFinishAllListeners()
                .toMatchValues(logic, {
                    trendSeries: expect.arrayContaining([
                        expect.objectContaining({ data: [100, 50, 75] }),
                        expect.objectContaining({ data: [100, 50, 75] }),
                    ]),
                })
        })
    })
})
