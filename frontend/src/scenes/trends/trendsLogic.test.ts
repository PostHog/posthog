import { expectLogic } from 'kea-test-utils'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightShortId } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import secondaryOptionsResults from './__fixtures__/insight-with-secondary-axis-options.json'

const Insight123 = '123' as InsightShortId
const Insight567 = '567' as InsightShortId

describe('trendsLogic', () => {
    let logic: ReturnType<typeof trendsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights': (req) => {
                    const short_id = req.url.searchParams.get('short_id')
                    if (short_id === Insight567) {
                        return [200, { results: [secondaryOptionsResults] }]
                    }
                    return [200, { results: ['result from api'] }]
                },
            },
        })
        initKeaTests()
    })

    describe('indexed results as datasets', () => {
        beforeEach(async () => {
            const props = { dashboardItemId: Insight567 }
            const theInsightLogic = insightLogic(props)
            theInsightLogic.mount()
            await expectLogic(theInsightLogic).toDispatchActions(['loadInsight']).toFinishAllListeners()

            logic = trendsLogic(props)
            logic.mount()
        })

        it('can collapse time series to use second axis choice', async () => {
            await expectLogic(logic).delay(5).toFinishAllListeners().toMatchValues({
                insight: secondaryOptionsResults,
            })

            expect(logic.values.indexedResults).toHaveLength(1)
            expect(logic.values.indexedResults[0].label).toEqual('$pageview')

            /**
             * data for checkout as second axis has
             * [
             *       0,
             *       0,
             *       0,
             *       0,
             *       0,
             *       0,
             *       643,
             *       0
             *     ]
             *
             *  and data for $pageview is
             *
             * [
             *       0,
             *       0,
             *       0,
             *       0,
             *       0,
             *       116,
             *       13549,
             *       0
             *     ]
             *
             *     since this is total count we expect
             *
             *     checkout [0, 643] and pageview [116, 13549]
             */
            expect(logic.values.indexedResults[0].data).toEqual([116, 13549])
            expect(logic.values.indexedResults[0].labels).toEqual(['0', '643'])
        })
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            const theInsightLogic = insightLogic(props)
            theInsightLogic.mount()
            await expectLogic(theInsightLogic).toDispatchActions(['loadInsight']).toFinishAllListeners()

            logic = trendsLogic(props)
            logic.mount()
        })

        it('setFilters calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{ id: 42 }] })
            })
                .toDispatchActions([
                    (action) =>
                        action.type === insightLogic(props).actionTypes.setFilters &&
                        action.payload.filters?.events?.[0]?.id === 42,
                ])
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
        })

        it('insightLogic.setFilters updates filters', async () => {
            await expectLogic(logic, () => {
                insightLogic(props).actions.setFilters({ events: [{ id: 42 }] })
            })
                .toMatchValues(logic, {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
                .toMatchValues(insightLogic(props), {
                    filters: expect.objectContaining({
                        events: [{ id: 42 }],
                    }),
                })
        })
    })
})
