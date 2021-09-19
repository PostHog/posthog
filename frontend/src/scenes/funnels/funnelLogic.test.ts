import { BuiltLogic } from 'kea'
import { funnelLogic } from './funnelLogic'
import { funnelLogicType } from './funnelLogicType'
import { api, mockAPI } from 'lib/api.mock'
import { expectLogic, testUtilsPlugin } from '~/test/kea-test-utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { initKea } from '~/initKea'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { funnelsModel } from '~/models/funnelsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'

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
        } else if (pathname === 'api/users/@me/') {
            return {}
        } else {
            debugger
            throw new Error()
        }
    })

    beforeEach(() => {
        initKea({ beforePlugins: [testUtilsPlugin] })
        posthog.init('no token', {
            api_host: 'borked',
            test: true,
            autocapture: false,
            disable_session_recording: true,
            advanced_disable_decide: true,
            opt_out_capturing_by_default: true,
            loaded: (p) => {
                p.opt_out_capturing()
            },
        })

        logic = funnelLogic({
            filters: {
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                ],
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

        it('sets filters in rawResults after load if valid', async () => {
            await expectLogic(logic)
                .toMatchValues({
                    rawResults: {
                        filters: {},
                        results: [],
                        timeConversionResults: { average_conversion_time: 0, bins: [] },
                    },
                    filters: {
                        actions: [
                            { id: '$pageview', order: 0 },
                            { id: '$pageview', order: 1 },
                        ],
                    },
                    areFiltersValid: true,
                })
                .toDispatchActions(['loadResultsSuccess'])
                .toMatchValues({
                    rawResults: {
                        filters: {
                            actions: [
                                { id: '$pageview', order: 0 },
                                { id: '$pageview', order: 1 },
                            ],
                        },
                        results: [],
                        timeConversionResults: { average_conversion_time: 0, bins: [] },
                    },
                    filters: {
                        actions: [
                            { id: '$pageview', order: 0 },
                            { id: '$pageview', order: 1 },
                        ],
                    },
                    areFiltersValid: true,
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
        // must add this for some reason
        featureFlagLogic.mount()
        await expectLogic(featureFlagLogic).toFinishAllListeners()

        // wait for clickhouse features to be enabled, otherwise this won't auto-reload
        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.setFilters({
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                    { id: '$pageview', order: 2 },
                ],
                breakdown: '$active_feature_flags',
            })
        })
            .toDispatchActions(['setFilters'])
            .toMatchValues({
                apiParams: expect.objectContaining({
                    breakdown: undefined,
                    breakdown_type: undefined,
                }),
            })
            .toDispatchActions(['loadResults', 'loadResultsSuccess'])

        expect(api.create.mock.calls[api.create.mock.calls.length - 1][1]).toMatchObject({
            actions: [
                { id: '$pageview', order: 0 },
                { id: '$pageview', order: 1 },
                { id: '$pageview', order: 2 },
            ],
            breakdown: undefined,
            breakdown_type: undefined,
            insight: 'FUNNELS',
            interval: 'day',
        })
    })
})
