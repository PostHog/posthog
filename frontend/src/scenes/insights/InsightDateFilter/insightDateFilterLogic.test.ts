import { initKeaTestLogic } from '~/test/init'
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

    initKeaTestLogic({
        logic: insightDateFilterLogic,
        props,
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('mounts all sorts of logics', async () => {
            await expectLogic(logic).toMount([insightLogic(props)])
        })
    })

    describe('date from and date to', () => {
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
                        dateFrom: '2021-12-13',
                        dateTo: '2021-12-14',
                    },
                })
        })

        initKeaTestLogic({
            logic: insightDateFilterLogic,
            props: {
                ...props,
                filters: {
                    date_from: '2021-12-13',
                    date_to: '2021-12-14',
                },
            },
            onLogic: (l) => (logic = l),
        })

        it('syncs with insightLogic filter dates', () => {
            expectLogic(logic).toMatchValues({ filters: { date_from: '2021-12-13', date_to: '2021-12-14' } })
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
