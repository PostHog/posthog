import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { useAvailableFeatures } from '~/mocks/features'
import { useMocks } from '~/mocks/jest'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, CorrelationConfigType, InsightLogicProps, InsightShortId } from '~/types'

import { DEFAULT_EXCLUDED_PERSON_PROPERTIES, funnelPropertyCorrelationLogic } from './funnelPropertyCorrelationLogic'

const Insight123 = '123' as InsightShortId

describe('funnelPropertyCorrelationLogic', () => {
    const props = { dashboardItemId: Insight123, syncWithUrl: true }
    let logic: ReturnType<typeof funnelPropertyCorrelationLogic.build>
    const correlationConfig: CorrelationConfigType = {}

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.CORRELATION_ANALYSIS, AvailableFeature.GROUP_ANALYTICS])
        useMocks({
            get: {
                '/api/environments/@current': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_TEAM,
                        correlation_config: correlationConfig,
                    },
                ],
                '/api/environments/:team_id/insights/': { results: [{}] },
                '/api/environments/:team_id/insights/:id/': {},
                '/api/projects/:team/groups_types/': [],
                '/api/environments/:team_id/persons/properties': [
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
                '/api/environments/:id': (req) => [
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
                '/api/environments/:team_id/insights/funnel/correlation': (req) => {
                    const data = req.body as any
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
                },
            },
        })
        initKeaTests(false)
        window.POSTHOG_APP_CONTEXT = undefined // to force API request to /api/environments/@current
    })

    const defaultProps: InsightLogicProps = {
        dashboardItemId: undefined,
        cachedInsight: {
            short_id: undefined,
            query: {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.FunnelsQuery,
                    series: [
                        { kind: NodeKind.ActionsNode, id: 1 },
                        { kind: NodeKind.ActionsNode, id: 1 },
                    ],
                },
            } as InsightVizNode,
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
})
