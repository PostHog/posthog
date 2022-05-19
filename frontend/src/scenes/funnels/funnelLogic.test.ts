import { DEFAULT_EXCLUDED_PERSON_PROPERTIES, funnelLogic } from './funnelLogic'
import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'
import posthog from 'posthog-js'
import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import {
    AvailableFeature,
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelCorrelationType,
    FunnelVizType,
    InsightLogicProps,
    InsightShortId,
    InsightType,
    TeamType,
} from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { groupPropertiesModel } from '~/models/groupPropertiesModel'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { useMocks } from '~/mocks/jest'
import { useAvailableFeatures } from '~/mocks/features'
import api from 'lib/api'

const Insight12 = '12' as InsightShortId
const Insight123 = '123' as InsightShortId

export const mockInsight = {
    id: Insight123,
    short_id: 'SvoU2bMC',
    name: null,
    filters: {
        breakdown: null,
        breakdown_type: null,
        display: 'FunnelViz',
        events: [
            {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                properties: [],
            },
            {
                id: '$pageview',
                type: 'events',
                order: 1,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                properties: [],
            },
            {
                id: '$pageview',
                type: 'events',
                order: 2,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                properties: [],
            },
            {
                id: '$pageview',
                type: 'events',
                order: 3,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                properties: [],
            },
        ],
        funnel_from_step: 0,
        funnel_to_step: 1,
        funnel_viz_type: 'steps',
        insight: 'FUNNELS',
        interval: 'day',
        layout: 'vertical',
    },
    filters_hash: 'cache_d0d88afd2fd8dd2af0b7f2e505588e99',
    order: null,
    deleted: false,
    dashboard: null,
    layouts: {},
    color: null,
    last_refresh: null,
    refreshing: false,
    result: null,
    created_at: '2021-09-22T18:22:20.036153Z',
    description: null,
    updated_at: '2021-09-22T19:03:49.322258Z',
    tags: [],
    favorited: false,
    saved: false,
    created_by: {
        id: 1,
        uuid: '017c0441-bcb2-0000-bccf-dfc24328c5f3',
        distinct_id: 'fM7b6ZFi8MOssbkDI55ot8tMY2hkzrHdRy1qERa6rCK',
        first_name: 'Alex',
        email: 'alex@posthog.com',
    },
}

const funnelResults = [
    {
        action_id: '$pageview',
        count: 19,
        name: '$pageview',
        order: 0,
        type: 'events',
    },
    {
        action_id: '$pageview',
        count: 7,
        name: '$pageview',
        order: 1,
        type: 'events',
    },
    {
        action_id: '$pageview',
        count: 4,
        name: '$pageview',
        order: 2,
        type: 'events',
    },
]

describe('funnelLogic', () => {
    let logic: ReturnType<typeof funnelLogic.build>
    let correlationConfig: TeamType['correlation_config'] = {}

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.CORRELATION_ANALYSIS, AvailableFeature.GROUP_ANALYTICS])
        useMocks({
            get: {
                '/api/projects/@current': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_TEAM,
                        correlation_config: correlationConfig,
                    },
                ],
                '/api/projects/:team/insights/': (req) => {
                    if (req.url.searchParams.get('saved')) {
                        return [
                            200,
                            {
                                results: funnelResults,
                            },
                        ]
                    }
                    const shortId = req.url.searchParams.get('short_id') || ''
                    if (shortId === '500') {
                        return [500, { status: 0, detail: 'error from the API' }]
                    }
                    return [
                        200,
                        {
                            results: [mockInsight],
                        },
                    ]
                },
                '/api/projects/:team/insights/trend/': { results: ['trends result from api'] },
                '/api/projects/:team/groups_types/': [],
                '/some/people/url': { results: [{ people: [] }] },
                '/api/person/funnel': { results: [], next: null },
                '/api/person/properties': [
                    { name: 'some property', count: 20 },
                    { name: 'another property', count: 10 },
                    { name: 'third property', count: 5 },
                ],
                '/api/projects/:team/groups/property_definitions': {
                    '0': [
                        { name: 'industry', count: 2 },
                        { name: 'name', count: 1 },
                    ],
                    '1': [{ name: 'name', count: 1 }],
                },
            },
            patch: {
                '/api/projects/:id': (req) => [
                    200,
                    {
                        ...MOCK_DEFAULT_TEAM,
                        correlation_config: {
                            ...correlationConfig,
                            excluded_person_property_names: (req.body as any)?.correlation_config
                                ?.excluded_person_property_names,
                        },
                    },
                ],
            },
            post: {
                '/api/projects/:team/insights/': (req) => [
                    200,
                    { id: 12, short_id: Insight12, ...((req.body as any) || {}) },
                ],
                '/api/projects/:team/insights/:id/viewed': [201],
                '/api/projects/:team/insights/funnel/': {
                    is_cached: true,
                    last_refresh: '2021-09-16T13:41:41.297295Z',
                    result: funnelResults,
                    type: 'Funnel',
                },
                '/api/projects/:team/insights/funnel/correlation': (req) => {
                    const data = req.body as any
                    if (data?.funnel_correlation_type === 'properties') {
                        const excludePropertyFromProjectNames = data?.funnel_correlation_exclude_names || []
                        const includePropertyNames = data?.funnel_correlation_names || []
                        return [
                            200,
                            {
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
                                        .filter(
                                            (correlation) =>
                                                !excludePropertyFromProjectNames.includes(correlation.event.event)
                                        ),
                                },
                                type: 'Funnel',
                            },
                        ]
                    } else if (data?.funnel_correlation_type === 'events') {
                        return [
                            200,
                            {
                                is_cached: true,
                                last_refresh: '2021-09-16T13:41:41.297295Z',
                                result: {
                                    events: [
                                        {
                                            event: { event: 'some event' },
                                            success_count: 1,
                                            failure_count: 1,
                                            odds_ratio: 1,
                                            correlation_type: 'success',
                                        },
                                        {
                                            event: { event: 'another event' },
                                            success_count: 1,
                                            failure_count: 1,
                                            odds_ratio: 1,
                                            correlation_type: 'failure',
                                        },
                                    ],
                                },
                                type: 'Funnel',
                            },
                        ]
                    } else if (data?.funnel_correlation_type === 'event_with_properties') {
                        const targetEvent = data?.funnel_correlation_event_names[0]
                        const excludedProperties = data?.funnel_correlation_event_exclude_property_names
                        return [
                            200,
                            {
                                result: {
                                    events: [
                                        {
                                            success_count: 1,
                                            failure_count: 0,
                                            odds_ratio: 29,
                                            correlation_type: 'success',
                                            event: { event: `some event::name::Hester` },
                                        },
                                        {
                                            success_count: 1,
                                            failure_count: 0,
                                            odds_ratio: 29,
                                            correlation_type: 'success',
                                            event: { event: `some event::Another name::Alice` },
                                        },
                                        {
                                            success_count: 1,
                                            failure_count: 0,
                                            odds_ratio: 25,
                                            correlation_type: 'success',
                                            event: { event: `another event::name::Aloha` },
                                        },
                                        {
                                            success_count: 1,
                                            failure_count: 0,
                                            odds_ratio: 25,
                                            correlation_type: 'success',
                                            event: { event: `another event::Another name::Bob` },
                                        },
                                    ].filter(
                                        (record) =>
                                            record.event.event.split('::')[0] === targetEvent &&
                                            !excludedProperties.includes(record.event.event.split('::')[1])
                                    ),
                                    last_refresh: '2021-11-05T09:26:16.175923Z',
                                    is_cached: false,
                                },
                            },
                        ]
                    }
                },
            },
        })
        initKeaTests(false)
        window.POSTHOG_APP_CONTEXT = undefined // to force API request to /api/project/@current
    })

    const defaultProps: InsightLogicProps = {
        dashboardItemId: undefined,
        cachedInsight: {
            short_id: undefined,
            filters: {
                insight: InsightType.FUNNELS,
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                ],
            },
            result: null,
        },
    }

    async function initFunnelLogic(props: InsightLogicProps = defaultProps): Promise<void> {
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        userLogic.mount()
        await expectLogic(userLogic).toFinishAllListeners()
        logic = funnelLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    describe('core assumptions', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })

        it('mounts all sorts of logics', async () => {
            await expectLogic(logic).toMount([
                eventUsageLogic,
                insightLogic({ dashboardItemId: undefined }),
                preflightLogic,
            ])
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
        })

        it('sets filters after load if valid', async () => {
            await expectLogic(logic)
                .toDispatchActions(['loadResults'])
                .toMatchValues({
                    insight: expect.objectContaining({
                        short_id: undefined,
                        filters: {
                            insight: InsightType.FUNNELS,
                            actions: [
                                { id: '$pageview', order: 0 },
                                { id: '$pageview', order: 1 },
                            ],
                        },
                        result: null,
                    }),
                    filters: {
                        insight: InsightType.FUNNELS,
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
                            insight: InsightType.FUNNELS,
                            actions: [
                                { id: '$pageview', order: 0 },
                                { id: '$pageview', order: 1 },
                            ],
                        },
                        result: expect.arrayContaining([expect.objectContaining({ count: 19 })]),
                    }),
                    filters: {
                        insight: InsightType.FUNNELS,
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
        beforeEach(async () => {
            await initFunnelLogic()
        })

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
        jest.spyOn(api, 'create')
        await initFunnelLogic()

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
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            await initFunnelLogic(props)
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

    describe('it is connected with personsModalLogic', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            await initFunnelLogic(props)
        })

        it('setFilters calls personsModalLogic.loadPeople', async () => {
            personsModalLogic.mount()
            await expectLogic().toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
            await expectLogic(() => {
                router.actions.push(urls.insightEdit(Insight123))
            })

            await expectLogic(logic, () => {
                logic.actions.openPersonsModalForStep({
                    step: {
                        action_id: '$pageview',
                        average_conversion_time: 0,
                        median_conversion_time: 0,
                        count: 1,
                        name: '$pageview',
                        order: 0,
                        type: 'events',
                        converted_people_url: '/some/people/url',
                        dropped_people_url: '/some/people/url',
                    },
                    converted: true,
                })
            }).toDispatchActions([
                (action) => {
                    return (
                        action.type === personsModalLogic.actionTypes.loadPeopleFromUrl &&
                        action.payload?.label === '$pageview'
                    )
                },
            ])
        })
    })

    describe('selectors', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })
        describe('Correlation Names parsing', () => {
            const basicFunnelRecord: FunnelCorrelation = {
                event: { event: '$pageview::bzzz', properties: {}, elements: [] },
                odds_ratio: 1,
                correlation_type: FunnelCorrelationType.Success,
                success_count: 1,
                failure_count: 1,
                success_people_url: '/some/people/url',
                failure_people_url: '/some/people/url',
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

    describe('funnel correlation matrix', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })
        it('Selecting a record returns appropriate values', async () => {
            await expectLogic(logic, () =>
                logic.actions.setFunnelCorrelationDetails({
                    event: { event: 'some event', elements: [], properties: {} },
                    success_people_url: '',
                    failure_people_url: '',
                    success_count: 2,
                    failure_count: 4,
                    odds_ratio: 3,
                    correlation_type: FunnelCorrelationType.Success,
                    result_type: FunnelCorrelationResultsType.Events,
                })
            ).toMatchValues({
                correlationMatrixAndScore: {
                    correlationScore: expect.anything(),
                    correlationScoreStrength: 'weak',
                    truePositive: 2,
                    falsePositive: 2,
                    trueNegative: 11,
                    falseNegative: 4,
                },
            })

            expect(logic.values.correlationMatrixAndScore.correlationScore).toBeCloseTo(0.204)
        })
    })

    describe('funnel correlation properties', () => {
        const props = { dashboardItemId: Insight123, syncWithUrl: true }

        it('Selecting all properties returns expected result', async () => {
            await initFunnelLogic(props)
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
            await initFunnelLogic(props)
            await expectLogic(logic, () => logic.actions.setPropertyNames([]))
                .toDispatchActions(logic, ['loadPropertyCorrelationsSuccess'])
                .toMatchValues({
                    propertyCorrelations: {
                        events: [],
                    },
                })
        })

        // TODO: loading of property correlations is now dependent on the table being shown in react
        it.skip('are updated when results are loaded, when steps visualisation set', async () => {
            await initFunnelLogic(props)
            const filters = {
                insight: InsightType.FUNNELS,
                funnel_viz_type: FunnelVizType.Steps,
            }
            await router.actions.push(urls.insightNew(filters))

            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({
                    steps: [
                        { action_id: '$pageview', count: 19, name: '$pageview', order: 0, type: 'events' },
                        { action_id: '$pageview', count: 7, name: '$pageview', order: 1, type: 'events' },
                        { action_id: '$pageview', count: 4, name: '$pageview', order: 2, type: 'events' },
                    ],
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
        it('are not updated when results are loaded, when steps visualisation set, with one funnel step', async () => {
            await initFunnelLogic(props)

            await expectLogic(logic, () => {
                logic.actions.loadResultsSuccess({
                    filters: { insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Steps },
                    result: [{ action_id: 'some event', order: 0 }],
                })
            })
                .toFinishListeners()
                .toMatchValues({
                    steps: [{ action_id: 'some event', order: 0 }],
                    propertyCorrelations: {
                        events: [],
                    },
                    correlations: {
                        events: [],
                    },
                })
        })
        it('are not triggered when results are loaded, when trends visualisation set', async () => {
            await initFunnelLogic(props)
            await expectLogic(logic, () => {
                logic.actions.loadResultsSuccess({
                    filters: { insight: InsightType.FUNNELS, funnel_viz_type: FunnelVizType.Trends },
                })
            }).toNotHaveDispatchedActions(['loadCorrelations', 'loadPropertyCorrelations'])
        })

        it('triggers update to correlation list when property excluded from project', async () => {
            userLogic.mount()
            await initFunnelLogic(props)
            //
            // // Make sure we have loaded the team already
            // await expectLogic(teamLogic, () => teamLogic.actions.loadCurrentTeam()).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setPropertyNames(logic.values.allProperties)
                logic.actions.loadResultsSuccess({ filters: { insight: InsightType.FUNNELS } })
                logic.actions.excludePropertyFromProject('another property')
            })
                .toFinishAllListeners()
                .toMatchValues({
                    propertyNames: ['some property', 'third property'],
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
            await initFunnelLogic(props)

            expect(logic.values.isPropertyExcludedFromProject('some property')).toBe(false)

            await expectLogic(logic, () =>
                logic.actions.excludePropertyFromProject('some property')
            ).toFinishAllListeners()

            expect(logic.values.isPropertyExcludedFromProject('some property')).toBe(true)

            await expectLogic(teamLogic).toMatchValues({
                currentTeam: partial({
                    correlation_config: {
                        excluded_person_property_names: DEFAULT_EXCLUDED_PERSON_PROPERTIES.concat(['some property']),
                    },
                }),
            })

            // Also make sure that excluding the property again doesn't double
            // up on the config list
            await expectLogic(logic, () =>
                logic.actions.excludePropertyFromProject('some property')
            ).toFinishAllListeners()

            await expectLogic(teamLogic).toMatchValues({
                currentTeam: partial({
                    correlation_config: {
                        excluded_person_property_names: DEFAULT_EXCLUDED_PERSON_PROPERTIES.concat(['some property']),
                    },
                }),
            })
        })

        it('loads property exclude list from Project settings', async () => {
            correlationConfig = { excluded_person_property_names: ['some property'] }
            await initFunnelLogic(props)

            await expectLogic(teamLogic).toMatchValues({
                currentTeam: partial({
                    correlation_config: { excluded_person_property_names: ['some property'] },
                }),
            })

            await expectLogic(logic, () => {
                logic.actions.setPropertyNames(logic.values.allProperties)
                logic.actions.loadResultsSuccess({ filters: { insight: InsightType.FUNNELS } })
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

        // TODO: loading of correlations is now dependent on the table being shown in react
        it.skip('loads event exclude list from Project settings', async () => {
            correlationConfig = { excluded_event_names: ['some event'] }
            await initFunnelLogic(props)

            await expectLogic(teamLogic).toMatchValues({
                currentTeam: partial({
                    correlation_config: { excluded_event_names: ['some event'] },
                }),
            })

            const filters = {
                insight: InsightType.FUNNELS,
                funnel_viz_type: FunnelVizType.Steps,
            }
            await router.actions.push(urls.insightNew(filters))

            await expectLogic(logic)
                .toFinishAllListeners()
                .toMatchValues({
                    correlationValues: [
                        {
                            event: { event: 'another event' },
                            success_count: 1,
                            failure_count: 1,
                            odds_ratio: 1,
                            correlation_type: 'failure',
                            result_type: FunnelCorrelationResultsType.Events,
                        },
                    ],
                })
        })

        it('loads event property exclude list from Project settings', async () => {
            correlationConfig = { excluded_event_property_names: ['name'] }
            await initFunnelLogic(props)

            await expectLogic(teamLogic).toMatchValues({
                currentTeam: partial({
                    correlation_config: { excluded_event_property_names: ['name'] },
                }),
            })

            await expectLogic(logic, () => {
                logic.actions.loadEventWithPropertyCorrelations('some event')
            })
                .toDispatchActions(logic, ['loadEventWithPropertyCorrelationsSuccess'])
                .toFinishListeners()
                .toMatchValues({
                    eventWithPropertyCorrelations: {
                        'some event': [
                            {
                                event: { event: 'some event::Another name::Alice' },
                                success_count: 1,
                                failure_count: 0,
                                odds_ratio: 29,
                                correlation_type: 'success',
                                result_type: FunnelCorrelationResultsType.EventWithProperties,
                            },
                        ],
                    },
                })
        })

        // TODO: fix this test
        it.skip('Selecting all group properties selects correct properties', async () => {
            await initFunnelLogic(props)

            groupPropertiesModel.mount()
            groupPropertiesModel.actions.loadAllGroupProperties()
            await expectLogic(groupPropertiesModel).toDispatchActions(['loadAllGroupPropertiesSuccess'])

            const filters = {
                insight: InsightType.FUNNELS,
                funnel_viz_type: FunnelVizType.Steps,
            }
            await router.actions.push(urls.insightNew(filters))
            console.log(router.values.location)

            await expectLogic(logic, () => logic.actions.setFilters({ aggregation_group_type_index: 0 }))
                .toFinishAllListeners()
                .toMatchValues({
                    allProperties: ['industry', 'name'],
                    propertyNames: ['industry', 'name'],
                })

            await expectLogic(logic, () => logic.actions.setFilters({ aggregation_group_type_index: 1 }))
                .toFinishAllListeners()
                .toMatchValues({
                    allProperties: ['name'],
                    propertyNames: ['name'],
                })
        })
    })

    describe('Correlation Feedback flow', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })
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
            jest.spyOn(posthog, 'capture')
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
            jest.spyOn(posthog, 'capture')
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

    describe('funnel simple vs. advanced mode', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })
        it("toggleAdvancedMode() doesn't trigger a load result", async () => {
            await expectLogic(logic, () => {
                logic.actions.toggleAdvancedMode()
            })
                .toDispatchActions(['toggleAdvancedMode', 'setFilters'])
                .toNotHaveDispatchedActions([
                    insightLogic({ dashboardItemId: Insight123 }).actionCreators.loadResults(),
                ])
        })
    })

    describe('is modal active', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })
        it('modal is inactive when viewed on dashboard', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await router.actions.push(urls.dashboard('1'))
            await expectLogic(logic).toMatchValues({
                isModalActive: false,
            })
        })
        it('modal is active when viewing insight', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await router.actions.push(urls.insightView('1' as InsightShortId))
            await expectLogic(logic).toMatchValues({
                isModalActive: true,
            })
        })
        it('modal is active when editing insight', async () => {
            await expectLogic(preflightLogic).toDispatchActions(['loadPreflightSuccess'])
            await router.actions.push(urls.insightEdit('1' as InsightShortId))
            await expectLogic(logic).toMatchValues({
                isModalActive: true,
            })
        })
    })
})
