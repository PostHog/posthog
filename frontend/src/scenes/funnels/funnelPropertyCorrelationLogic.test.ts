import { expectLogic, partial } from 'kea-test-utils'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AvailableFeature,
    CorrelationConfigType,
    FunnelCorrelationResultsType,
    InsightLogicProps,
    InsightShortId,
    InsightType,
} from '~/types'
import { DEFAULT_EXCLUDED_PERSON_PROPERTIES, funnelPropertyCorrelationLogic } from './funnelPropertyCorrelationLogic'

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

describe('funnelPropertyCorrelationLogic', () => {
    const props = { dashboardItemId: Insight123, syncWithUrl: true }
    let logic: ReturnType<typeof funnelPropertyCorrelationLogic.build>
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
        // window.POSTHOG_APP_CONTEXT = undefined // to force API request to /api/project/@current
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

    async function initPropertyFunnelCorrelationLogic(props: InsightLogicProps = defaultProps): Promise<void> {
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        userLogic.mount()
        await expectLogic(userLogic).toFinishAllListeners()
        logic = funnelPropertyCorrelationLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('Selecting all properties returns expected result', async () => {
        await initPropertyFunnelCorrelationLogic(props)
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
        await initPropertyFunnelCorrelationLogic(props)
        await expectLogic(logic, () => logic.actions.setPropertyNames([]))
            .toDispatchActions(logic, ['loadPropertyCorrelationsSuccess'])
            .toMatchValues({
                propertyCorrelations: {
                    events: [],
                },
            })
    })

    it('isPropertyExcludedFromProject returns true initially, then false when excluded, and is persisted to team config', async () => {
        await initPropertyFunnelCorrelationLogic(props)

        expect(logic.values.isPropertyExcludedFromProject('some property')).toBe(false)

        await expectLogic(logic, () => logic.actions.excludePropertyFromProject('some property')).toFinishAllListeners()

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
        await expectLogic(logic, () => logic.actions.excludePropertyFromProject('some property')).toFinishAllListeners()

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
        await initPropertyFunnelCorrelationLogic(props)

        await expectLogic(teamLogic).toMatchValues({
            currentTeam: partial({
                correlation_config: { excluded_person_property_names: ['some property'] },
            }),
        })

        await expectLogic(logic, () => {
            logic.actions.setPropertyNames(logic.values.allProperties)
            // logic.actions.loadResultsSuccess({ filters: { insight: InsightType.FUNNELS } })
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
