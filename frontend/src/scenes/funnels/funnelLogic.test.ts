import { DEFAULT_EXCLUDED_PERSON_PROPERTIES, funnelLogic } from './funnelLogic'
import { MOCK_DEFAULT_TEAM, MOCK_TEAM_ID } from 'lib/api.mock'
import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import {
    AvailableFeature,
    CorrelationConfigType,
    FunnelCorrelationResultsType,
    FunnelsFilterType,
    FunnelVizType,
    InsightLogicProps,
    InsightShortId,
    InsightType,
} from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { useMocks } from '~/mocks/jest'
import { useAvailableFeatures } from '~/mocks/features'
import api from 'lib/api'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'

jest.mock('scenes/trends/persons-modal/PersonsModal')

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
        layout: 'vertical',
    },
    order: null,
    deleted: false,
    dashboard: null,
    layouts: {},
    color: null,
    last_refresh: null,
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
    let correlationConfig: CorrelationConfigType = {}

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
                '/api/projects/:team/persons/funnel': { results: [], next: null },
                '/api/projects/:team/persons/properties': [
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
                    isFunnelWithEnoughSteps: true,
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
                    isFunnelWithEnoughSteps: true,
                })
        })
    })

    describe('isFunnelWithEnoughSteps', () => {
        beforeEach(async () => {
            await initFunnelLogic()
        })

        it('sets it properly', () => {
            expectLogic(logic, () => {
                logic.actions.setFilters({ actions: [] })
            }).toMatchValues({ isFunnelWithEnoughSteps: false })

            expectLogic(logic, () => {
                logic.actions.setFilters({})
            }).toMatchValues({ isFunnelWithEnoughSteps: false })

            expectLogic(logic, () => {
                logic.actions.setFilters({ actions: [{}, {}] })
            }).toMatchValues({ isFunnelWithEnoughSteps: true })

            expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{}, {}] })
            }).toMatchValues({ isFunnelWithEnoughSteps: true })

            expectLogic(logic, () => {
                logic.actions.setFilters({ events: [{}], actions: [{ from: 'previous isFunnelWithEnoughSteps test' }] })
            }).toMatchValues({ isFunnelWithEnoughSteps: true })
        })
    })

    it("load results, don't send breakdown if old visualisation is shown", async () => {
        jest.spyOn(api, 'createResponse')
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

        expect(api.createResponse).toHaveBeenNthCalledWith(
            2,
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
            }),
            expect.anything()
        )
    })

    describe('syncs with insightLogic', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            await initFunnelLogic(props)
        })

        it('setFilters calls insightLogic.setFilters', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ insight: InsightType.FUNNELS, events: [{ id: 42 }] })
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
                insightLogic(props).actions.setFilters({ insight: InsightType.FUNNELS, events: [{ id: 42 }] })
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

    describe('it opens the PersonsModal', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            await initFunnelLogic(props)
        })

        test('openPersonsModalForStep calls openPersonsModal', async () => {
            await expectLogic().toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
            await expectLogic(() => {
                router.actions.push(urls.insightEdit(Insight123))
            })

            logic.actions.openPersonsModalForStep({
                step: {
                    action_id: '$pageview',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    count: 1,
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=USA',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=USA',
                },
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith({
                title: expect.any(Object),
                url: '/some/people/url?funnel_step=2', // Positive funnel_step and no funnel_step_breakdown
            })
        })

        test('openPersonsModalForSeries calls openPersonsModal', async () => {
            await expectLogic().toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
            await expectLogic(() => {
                router.actions.push(urls.insightEdit(Insight123))
            })

            logic.actions.openPersonsModalForSeries({
                series: {
                    action_id: '$pageview',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    count: 1,
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=Latvia',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=Latvia',
                    droppedOffFromPrevious: 0,
                    conversionRates: {
                        fromPrevious: 1,
                        total: 1,
                        fromBasisStep: 1,
                    },
                },
                step: {
                    action_id: '$pageview',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    count: 1,
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=USA',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=USA',
                },
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith({
                title: expect.any(Object),
                url: '/some/people/url?funnel_step=2&funnel_step_breakdown=Latvia', // Series funnel_step_breakdown included
            })
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

        it('are not triggered when results are loaded, when trends visualisation set', async () => {
            await initFunnelLogic(props)
            await expectLogic(logic, () => {
                logic.actions.loadResultsSuccess({
                    filters: {
                        insight: InsightType.FUNNELS,
                        funnel_viz_type: FunnelVizType.Trends,
                    } as FunnelsFilterType,
                })
            }).toNotHaveDispatchedActions(['loadEventCorrelations', 'loadPropertyCorrelations'])
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
})
