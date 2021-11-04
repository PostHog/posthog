import { DEFAULT_EXCLUDED_PERSON_PROPERTIES, funnelLogic } from './funnelLogic'
import { api, defaultAPIMocks, mockAPI, MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'
import posthog from 'posthog-js'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { funnelsModel } from '~/models/funnelsModel'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { FunnelCorrelation, FunnelCorrelationResultsType, FunnelCorrelationType, ViewType } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

jest.mock('lib/api')
jest.mock('posthog-js')

type CorrelationConfig = {
    excluded_person_property_names?: string[]
}

describe('funnelLogic', () => {
    let logic: ReturnType<typeof funnelLogic.build>
    let correlationConfig: CorrelationConfig = {}

    mockAPI(async (url) => {
        if (['api/projects/@current', `api/projects/${MOCK_TEAM_ID}`].includes(url.pathname)) {
            if (url.method === 'update') {
                correlationConfig = {
                    ...correlationConfig,
                    excluded_person_property_names: url.data?.correlation_config?.excluded_person_property_names,
                }
            }

            return {
                ...MOCK_DEFAULT_TEAM,
                correlation_config: correlationConfig,
            }
        } else if (url.pathname === `api/projects/${MOCK_TEAM_ID}/insights/funnel/`) {
            return {
                is_cached: true,
                last_refresh: '2021-09-16T13:41:41.297295Z',
                result: ['result from api'],
                type: 'Funnel',
            }
        } else if (
            url.pathname === `api/projects/${MOCK_TEAM_ID}/insights/funnel/correlation` &&
            url.data?.funnel_correlation_type === 'properties'
        ) {
            const excludePropertyFromProjectNames = url.data?.funnel_correlation_exclude_names || []
            const includePropertyNames = url.data?.funnel_correlation_names || []
            return {
                is_cached: true,
                last_refresh: '2021-09-16T13:41:41.297295Z',
                result: {
                    events: [
                        {
                            event: { event: 'some property' },
                            success_count: 1,
                            failure_count: 1,
                            odds_ratio: 1,
                            correlation_type: 'success',
                        },
                        {
                            event: { event: 'another property' },
                            success_count: 1,
                            failure_count: 1,
                            odds_ratio: 1,
                            correlation_type: 'failure',
                        },
                    ]
                        .filter(
                            (correlation) =>
                                includePropertyNames.includes('$all') ||
                                includePropertyNames.includes(correlation.event.event)
                        )
                        .filter((correlation) => !excludePropertyFromProjectNames.includes(correlation.event.event)),
                },
                type: 'Funnel',
            }
        } else if (
            url.pathname === `api/projects/${MOCK_TEAM_ID}/insights/funnel/correlation` &&
            url.data?.funnel_correlation_type === 'events'
        ) {
            return {
                is_cached: true,
                last_refresh: '2021-09-16T13:41:41.297295Z',
                result: {
                    events: [
                        { event: { event: 'some event' }, success_count: 1, failure_count: 1 },
                        { event: { event: 'another event' }, success_count: 1, failure_count: 1 },
                    ],
                },
                type: 'Funnel',
            }
        } else if (url.pathname.startsWith(`api/projects/${MOCK_TEAM_ID}/insights`)) {
            return { results: [], next: null }
        } else if (url.pathname === `api/person/properties`) {
            return [
                { name: 'some property', count: 20 },
                { name: 'another property', count: 10 },
                { name: 'third property', count: 5 },
            ]
        }
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: funnelLogic,
        props: {
            dashboardItemId: undefined,
            filters: {
                insight: ViewType.FUNNELS,
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                ],
            },
        },
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('mounts all sorts of logics', async () => {
            await expectLogic(logic).toMount([
                eventUsageLogic,
                insightLogic({ dashboardItemId: undefined }),
                insightHistoryLogic,
                preflightLogic,
                funnelsModel,
            ])
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await expectLogic(funnelsModel).toDispatchActions(['loadFunnelsSuccess'])
        })

        it('has clickhouse enabled once preflight loads', async () => {
            await expectLogic()
                .toDispatchActions(preflightLogic, ['loadPreflight'])
                .toMatchValues(logic, {
                    clickhouseFeaturesEnabled: false,
                })
                .toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
                .toMatchValues(logic, {
                    clickhouseFeaturesEnabled: true,
                })
        })

        it('sets filters after load if valid', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadResults'])
                .toMatchValues({
                    insight: expect.objectContaining({
                        id: undefined,
                        filters: {},
                        result: null,
                    }),
                    filters: {
                        insight: ViewType.FUNNELS,
                        actions: [
                            { id: '$pageview', order: 0 },
                            { id: '$pageview', order: 1 },
                        ],
                    },
                    areFiltersValid: true,
                })
                .toDispatchActions(['loadResultsSuccess'])
                .toMatchValues({
                    insight: expect.objectContaining({
                        filters: {
                            insight: ViewType.FUNNELS,
                            actions: [
                                { id: '$pageview', order: 0 },
                                { id: '$pageview', order: 1 },
                            ],
                        },
                        result: ['result from api'],
                    }),
                    filters: {
                        insight: ViewType.FUNNELS,
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
        beforeEach(async () => await expectLogic(logic).toFinishAllListeners())

        it('sets it properly', () => {
            expectLogic(logic, () => {
                logic.actions.setFilters({ actions: [] })
            }).toMatchValues({ areFiltersValid: false })

            expectLogic(logic, () => {
                logic.actions.setFilters({})
            }).toMatchValues({ areFiltersValid: false })

            expectLogic(logic, () => {
                logic.actions.setFilters({ actions: [{}, {}] })
            }).toMatchValues({ areFiltersValid: true })

            expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{}, {}] })
            }).toMatchValues({ areFiltersValid: true })

            expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{}], actions: [{ from: 'previous areFiltersValid test' }] })
            }).toMatchValues({ areFiltersValid: true })
        })
    })

    it("load results, don't send breakdown if old visualisation is shown", async () => {
        // wait for clickhouse features to be enabled, otherwise this won't call "loadResults"
        await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setFilters({
                actions: [],
                events: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                    { id: '$pageview', order: 2 },
                ],
                breakdown: '$active_feature_flags',
            })
        })
            .toDispatchActions(['setFilters', 'loadResults', 'loadResultsSuccess'])
            .toMatchValues({
                apiParams: expect.objectContaining({
                    actions: [],
                    events: [
                        { id: '$pageview', order: 0 },
                        { id: '$pageview', order: 1 },
                        { id: '$pageview', order: 2 },
                    ],
                    breakdown: undefined,
                    breakdown_type: undefined,
                }),
            })

        expect(api.create).toBeCalledWith(
            `api/projects/${MOCK_TEAM_ID}/insights/funnel/`,
            expect.objectContaining({
                actions: [],
                events: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                    { id: '$pageview', order: 2 },
                ],
                breakdown: undefined,
                breakdown_type: undefined,
                insight: 'FUNNELS',
                interval: 'day',
            })
        )
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: 123 }
        initKeaTestLogic({
            logic: funnelLogic,
            props,
            onLogic: (l) => (logic = l),
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

    describe('selectors', () => {
        describe('Correlation Names parsing', () => {
            const basicFunnelRecord: FunnelCorrelation = {
                event: { event: '$pageview::bzzz', properties: {}, elements: [] },
                odds_ratio: 1,
                correlation_type: FunnelCorrelationType.Success,
                success_count: 1,
                failure_count: 1,
                result_type: FunnelCorrelationResultsType.Events,
            }
            it('chooses the correct name based on Event type', async () => {
                const result = logic.values.parseDisplayNameForCorrelation(basicFunnelRecord)
                expect(result).toEqual({
                    first_value: '$pageview::bzzz',
                    second_value: undefined,
                })
            })

            it('chooses the correct name based on Property type', async () => {
                const result = logic.values.parseDisplayNameForCorrelation({
                    ...basicFunnelRecord,
                    result_type: FunnelCorrelationResultsType.Properties,
                })
                expect(result).toEqual({
                    first_value: '$pageview',
                    second_value: 'bzzz',
                })
            })

            it('chooses the correct name based on EventWithProperty type', async () => {
                const result = logic.values.parseDisplayNameForCorrelation({
                    ...basicFunnelRecord,
                    result_type: FunnelCorrelationResultsType.EventWithProperties,
                    event: {
                        event: '$pageview::library::1.2',
                        properties: { random: 'x' },
                        elements: [],
                    },
                })
                expect(result).toEqual({
                    first_value: 'library',
                    second_value: '1.2',
                })
            })

            it('handles autocapture events on EventWithProperty type', async () => {
                const result = logic.values.parseDisplayNameForCorrelation({
                    ...basicFunnelRecord,
                    result_type: FunnelCorrelationResultsType.EventWithProperties,
                    event: {
                        event: '$autocapture::elements_chain::xyz_elements_a.link*',
                        properties: { $event_type: 'click' },
                        elements: [
                            {
                                tag_name: 'a',
                                href: '#',
                                attributes: { blah: 'https://example.com' },
                                nth_child: 0,
                                nth_of_type: 0,
                                order: 0,
                                text: 'bazinga',
                            },
                        ],
                    },
                })
                expect(result).toEqual({
                    first_value: 'clicked link with text "bazinga"',
                    second_value: undefined,
                })
            })

            it('handles autocapture events without elements_chain on EventWithProperty type', async () => {
                const result = logic.values.parseDisplayNameForCorrelation({
                    ...basicFunnelRecord,
                    result_type: FunnelCorrelationResultsType.EventWithProperties,
                    event: {
                        event: '$autocapture::library::1.2',
                        properties: { random: 'x' },
                        elements: [],
                    },
                })
                expect(result).toEqual({
                    first_value: 'library',
                    second_value: '1.2',
                })
            })
        })
    })

    describe('funnel correlation properties', () => {
        // NOTE: we need to, in some of these tests, explicitly push the
        // teamLogic to update the currentTeam, and also explicitly mount the
        // userLogic.

        it('initially not loaded', async () => {
            await expectLogic(logic)
                .toFinishListeners()
                .toMatchValues({
                    propertyCorrelations: { events: [] },
                })
        })

        it('Selecting all properties returns expected result', async () => {
            featureFlagLogic.actions.setFeatureFlags(['correlation-analysis'], { 'correlation-analysis': true })

            await expectLogic(logic, () => logic.actions.setPropertyNames(logic.values.allProperties))
                .toFinishListeners()
                .toMatchValues({
                    propertyCorrelations: {
                        events: [
                            {
                                event: { event: 'some property' },
                                success_count: 1,
                                failure_count: 1,
                                odds_ratio: 1,
                                correlation_type: 'success',
                                result_type: FunnelCorrelationResultsType.Properties,
                            },
                            {
                                event: { event: 'another property' },
                                success_count: 1,
                                failure_count: 1,
                                odds_ratio: 1,
                                correlation_type: 'failure',
                                result_type: FunnelCorrelationResultsType.Properties,
                            },
                        ],
                    },
                })
        })

        it('Deselecting all returns empty result', async () => {
            await expectLogic(logic, () => logic.actions.setPropertyNames([]))
                .toFinishListeners()
                .toMatchValues({
                    propertyCorrelations: {
                        events: [],
                    },
                })
        })

        it('are updated when results are loaded, when feature flag set', async () => {
            featureFlagLogic.actions.setFeatureFlags(['correlation-analysis'], { 'correlation-analysis': true })

            await expectLogic(logic, () => {
                logic.actions.setPropertyNames(logic.values.allProperties)
                logic.actions.loadResultsSuccess({ filters: { insight: ViewType.FUNNELS } })
            })
                .toFinishListeners()
                .toMatchValues({
                    propertyCorrelations: {
                        events: [
                            {
                                event: { event: 'some property' },
                                success_count: 1,
                                failure_count: 1,
                                odds_ratio: 1,
                                correlation_type: 'success',
                                result_type: FunnelCorrelationResultsType.Properties,
                            },
                            {
                                event: { event: 'another property' },
                                success_count: 1,
                                failure_count: 1,
                                odds_ratio: 1,
                                correlation_type: 'failure',
                                result_type: FunnelCorrelationResultsType.Properties,
                            },
                        ],
                    },
                })
        })

        it('triggers update to correlation list when property excluded from project', async () => {
            featureFlagLogic.actions.setFeatureFlags(['correlation-analysis'], { 'correlation-analysis': true })
            userLogic.mount()

            // Make sure we have loaded the team already
            await expectLogic(teamLogic, () => teamLogic.actions.loadCurrentTeam()).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setPropertyNames(logic.values.allProperties)
                logic.actions.loadResultsSuccess({ filters: { insight: ViewType.FUNNELS } })
                logic.actions.excludePropertyFromProject('another property')
            })
                .toFinishAllListeners()
                .toMatchValues({
                    propertyNames: ['some property', 'another property', 'third property'],
                    excludedPropertyNames: DEFAULT_EXCLUDED_PERSON_PROPERTIES.concat(['another property']),
                    allProperties: ['some property', 'third property'],
                })

            expect(logic.values.propertyCorrelationValues).toEqual([
                {
                    event: { event: 'some property' },
                    success_count: 1,
                    failure_count: 1,
                    odds_ratio: 1,
                    correlation_type: 'success',
                    result_type: FunnelCorrelationResultsType.Properties,
                },
            ])
        })

        it('isPropertyExcludedFromProject returns true initially, then false when excluded, and is persisted to team config', async () => {
            userLogic.mount()

            expect(logic.values.isPropertyExcludedFromProject('some property')).toBe(false)

            await expectLogic(logic, () =>
                logic.actions.excludePropertyFromProject('some property')
            ).toFinishListeners()

            expect(logic.values.isPropertyExcludedFromProject('some property')).toBe(true)

            await expectLogic(teamLogic).toMatchValues({
                currentTeam: {
                    ...MOCK_DEFAULT_TEAM,
                    correlation_config: {
                        excluded_person_property_names: DEFAULT_EXCLUDED_PERSON_PROPERTIES.concat(['some property']),
                    },
                },
            })

            // Also make sure that excluding the property again doesn't double
            // up on the config list
            await expectLogic(logic, () =>
                logic.actions.excludePropertyFromProject('some property')
            ).toFinishListeners()

            await expectLogic(teamLogic).toMatchValues({
                currentTeam: {
                    ...MOCK_DEFAULT_TEAM,
                    correlation_config: {
                        excluded_person_property_names: DEFAULT_EXCLUDED_PERSON_PROPERTIES.concat(['some property']),
                    },
                },
            })
        })

        it('loads exclude list from Project settings', async () => {
            featureFlagLogic.actions.setFeatureFlags(['correlation-analysis'], { 'correlation-analysis': true })
            correlationConfig = { excluded_person_property_names: ['some property'] }

            // TODO: move api mocking to this test. I couldn't seem to figure
            // out how that would work with mockApi.
            await expectLogic(teamLogic, () => teamLogic.actions.loadCurrentTeam())
                .toFinishListeners()
                .toMatchValues({
                    currentTeam: {
                        ...MOCK_DEFAULT_TEAM,
                        correlation_config: { excluded_person_property_names: ['some property'] },
                    },
                })

            await expectLogic(logic, () => {
                logic.actions.setPropertyNames(logic.values.allProperties)
                logic.actions.loadResultsSuccess({ filters: { insight: ViewType.FUNNELS } })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    propertyCorrelations: {
                        events: [
                            {
                                event: { event: 'another property' },
                                success_count: 1,
                                failure_count: 1,
                                odds_ratio: 1,
                                correlation_type: 'failure',
                                result_type: FunnelCorrelationResultsType.Properties,
                            },
                        ],
                    },
                })
        })
    })

    describe('Correlation Feedback flow', () => {
        it('opens detailed feedback on selecting a valid rating', async () => {
            await expectLogic(logic, () => {
                logic.actions.setCorrelationFeedbackRating(1)
            })
                .toMatchValues(logic, {
                    correlationFeedbackRating: 1,
                })
                .toDispatchActions(logic, [
                    (action) =>
                        action.type === logic.actionTypes.setCorrelationDetailedFeedbackVisible &&
                        action.payload.visible === true,
                ])
                .toMatchValues(logic, {
                    correlationDetailedFeedbackVisible: true,
                })
        })

        it('doesnt opens detailed feedback on selecting an invalid rating', async () => {
            await expectLogic(logic, () => {
                logic.actions.setCorrelationFeedbackRating(0)
            })
                .toMatchValues(logic, {
                    correlationFeedbackRating: 0,
                })
                .toDispatchActions(logic, [
                    (action) =>
                        action.type === logic.actionTypes.setCorrelationDetailedFeedbackVisible &&
                        action.payload.visible === false,
                ])
                .toMatchValues(logic, {
                    correlationDetailedFeedbackVisible: false,
                })
        })

        it('Captures emoji feedback properly', async () => {
            await expectLogic(logic, () => {
                logic.actions.setCorrelationFeedbackRating(1)
            })
                .toMatchValues(logic, {
                    // reset after sending feedback
                    correlationFeedbackRating: 1,
                })
                .toDispatchActions(eventUsageLogic, ['reportCorrelationAnalysisFeedback'])

            expect(posthog.capture).toBeCalledWith('correlation analysis feedback', { rating: 1 })
        })

        it('goes away on sending feedback, capturing it properly', async () => {
            await expectLogic(logic, () => {
                logic.actions.setCorrelationFeedbackRating(2)
                logic.actions.setCorrelationDetailedFeedback('tests')
                logic.actions.sendCorrelationAnalysisFeedback()
            })
                .toMatchValues(logic, {
                    // reset after sending feedback
                    correlationFeedbackRating: 0,
                    correlationDetailedFeedback: '',
                    correlationFeedbackHidden: true,
                })
                .toDispatchActions(eventUsageLogic, ['reportCorrelationAnalysisDetailedFeedback'])
                .toFinishListeners()

            await expectLogic(eventUsageLogic).toFinishListeners()

            expect(posthog.capture).toBeCalledWith('correlation analysis feedback', { rating: 2 })
            expect(posthog.capture).toBeCalledWith('correlation analysis detailed feedback', {
                rating: 2,
                comments: 'tests',
            })
        })
    })
})
