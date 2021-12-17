import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { insightDateFilterLogic } from 'scenes/insights/InsightDateFilter/insightDateFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId } from '~/types'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'

jest.mock('lib/api')

describe('the insightDateFilterLogic', () => {
    let logic: ReturnType<typeof insightDateFilterLogic.build>
    const props = { dashboardItemId: 'test' as InsightShortId }

    mockAPI(async (url) => {
        return defaultAPIMocks(url)
    })

    beforeEach(() => {
        initKeaTests()
        insightLogic(props).mount()
        logic = insightDateFilterLogic(props)
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts all sorts of logics', async () => {
            await expectLogic(logic).toMount([insightLogic(logic.props)])
        })
    })

    describe('syncs with insightLogic', () => {
        it('setDates updates insightLogic filters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setDates('2020-02-01', '2020-02-11')
            }).toDispatchActions([
                insightLogic(logic.props).actionCreators.setFilters({ date_from: '2020-02-01', date_to: '2020-02-11' }),
            ])
        })
    })

    describe('date from and date to', () => {
        describe('use fallback date range', () => {
            it('use fallback date range when insight is set but filter is empty', async () => {
                await insightLogic(props).actions.setInsight(
                    {
                        result: [
                            {
                                filter: {
                                    date_from: '2020-01-12',
                                    date_to: '2020-03-12',
                                },
                            },
                        ],
                    },
                    {}
                )
                await expectLogic()
                    .toMatchValues(insightLogic(props), {
                        fallbackDateRange: expect.objectContaining({
                            dateFrom: '2020-01-12',
                            dateTo: '2020-03-12',
                        }),
                    })
                    .toMatchValues(logic, {
                        dates: {
                            dateFrom: '2020-01-12',
                            dateTo: '2020-03-12',
                        },
                    })
            })
        })

        describe("don't use fallback date range", () => {
            beforeEach(async () => {
                await insightLogic(props).actions.setFilters({
                    date_from: '2021-12-13',
                    date_to: '2021-12-14',
                })
            })

            it('syncs with insightLogic filter dates', async () => {
                await expectLogic(logic).toMatchValues({
                    filters: expect.objectContaining({ date_from: '2021-12-13', date_to: '2021-12-14' }),
                })
            })

            it("don't fallback date range when insight and filter is set", async () => {
                await insightLogic(props).actions.setInsight(
                    {
                        result: [
                            {
                                filter: {
                                    date_from: '2020-01-12',
                                    date_to: '2020-03-12',
                                },
                            },
                        ],
                    },
                    {}
                )
                await expectLogic()
                    .toMatchValues(insightLogic(props), {
                        fallbackDateRange: expect.objectContaining({
                            dateFrom: '2020-01-12',
                            dateTo: '2020-03-12',
                        }),
                    })
                    .toMatchValues(logic, {
                        dates: {
                            dateFrom: '2021-12-13',
                            dateTo: '2021-12-14',
                        },
                    })
            })
        })
    })
})
