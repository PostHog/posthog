import { mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { retentionTableLogic } from 'scenes/retention/retentionTableLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId, InsightType } from '~/types'

jest.mock('lib/api')

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

    mockAPI(async ({ pathname, searchParams }) => {
        if (String(searchParams.short_id) === Insight123) {
            return { results: [result] }
        } else if (
            [`api/projects/${MOCK_TEAM_ID}/insights`, `api/projects/${MOCK_TEAM_ID}/insights/trend/`].includes(pathname)
        ) {
            return { results: [] }
        } else if (pathname === `api/projects/${MOCK_TEAM_ID}/insights/retention/`) {
            return { result }
        }
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }
        initKeaTestLogic({
            logic: retentionTableLogic,
            props,
            onLogic: (l) => (logic = l),
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
