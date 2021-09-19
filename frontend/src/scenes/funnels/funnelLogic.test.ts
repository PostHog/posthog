import { BuiltLogic } from 'kea'
import { funnelLogic } from './funnelLogic'
import { funnelLogicType } from './funnelLogicType'
import { mockAPI } from 'lib/api.mock'
import { expectLogic, testUtilsPlugin } from '~/test/kea-test-utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { initKea } from '~/initKea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { funnelsModel } from '~/models/funnelsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'

jest.mock('lib/api')

describe('funnelLogic', () => {
    let logic: BuiltLogic<funnelLogicType>

    mockAPI(async ({ pathname }) => {
        if (pathname === 'api/insight/') {
            return { results: [], next: null }
        } else if (pathname === 'api/insight/funnel/') {
            return {
                is_cached: true,
                last_refresh: '2021-09-16T13:41:41.297295Z',
                result: [],
                type: 'Funnel',
            }
        } else if (pathname === '_preflight/') {
            return { is_clickhouse_enabled: true }
        } else {
            debugger
            throw new Error()
        }
    })

    beforeEach(() => {
        initKea({ beforePlugins: [testUtilsPlugin] })
        logic = funnelLogic({
            filters: {
                actions: [{ id: '$pageview', order: 0 }],
            },
        })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('mounts all sorts of logics', async () => {
            await expectLogic(logic).toMount([
                eventUsageLogic,
                insightLogic,
                insightHistoryLogic,
                preflightLogic,
                funnelsModel,
            ])
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(funnelsModel).toDispatchActions(['loadFunnelsSuccess'])
        })

        it('has clickhouse enabled once preflight loads', async () => {
            await expectLogic(logic).toMatchValues({
                clickhouseFeaturesEnabled: false,
            })
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(logic).toMatchValues({
                clickhouseFeaturesEnabled: true,
            })
        })

        it('loads all funnels on load', async () => {
            // starts with empty filters
            await expectLogic(logic).toMatchValues({
                rawResults: {
                    filters: {},
                    results: [],
                    timeConversionResults: { average_conversion_time: 0, bins: [] },
                },
            })
            // wait for things to quiet down
            await expectLogic(logic).toFinishAllListeners()
            // has the props filter, and a mocked API response
            await expectLogic(logic).toMatchValues({
                rawResults: {
                    filters: {
                        actions: [{ id: '$pageview', order: 0 }],
                    },
                    results: [],
                    timeConversionResults: { average_conversion_time: 0, bins: [] },
                },
            })
        })
    })

    describe('areFiltersValid', () => {
        beforeEach(() => expectLogic(logic).toFinishAllListeners())

        it('sets it properly', () => {
            expectLogic(logic, () => {
                logic.actions.setFilters({ actions: [] })
            }).toMatchValues({ areFiltersValid: false })

            expectLogic(logic, () => {
                logic.actions.setFilters({})
            }).toMatchValues({ areFiltersValid: false })
        })
    })

    it("Load results, don't send breakdown if old visualisation is shown", async () => {
        // wait for clickhouse features to be enabled, otherwise this won't auto-reload
        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        await expectLogic(logic, () => {
            logic.actions.setFilters({
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                ],
                breakdown: '$active_feature_flags',
            })
        })
            .toFinishListeners()
            .printActions()
            .toDispatchActions(['setFilters', 'loadResults', 'loadResultsSuccess'])

        // expect(api.create.mock.calls[0][1]).toMatchObject(
        //     {"actions": [{"id": "$pageview", "order": 0}], "funnel_window_days": 14, "insight": "FUNNELS", "interval": "day"}
        // )
    })
})
