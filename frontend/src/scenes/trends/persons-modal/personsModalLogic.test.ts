import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { FunnelsActorsQuery, FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PersonActorType, PropertyFilterType, PropertyOperator } from '~/types'

import { personsModalLogic } from './personsModalLogic'

describe('personsModalLogic', () => {
    let logic: ReturnType<typeof personsModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': () => [200, { results: [] }],
            },
        })
        initKeaTests()
    })

    describe('sessionIdsFromLoadedActors', () => {
        it('extracts session IDs from loaded actors with matched_recordings', () => {
            const mockActorsQuery = {
                kind: NodeKind.ActorsQuery,
                source: {
                    kind: NodeKind.FunnelsActorsQuery,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        series: [],
                    },
                    funnelStep: -2,
                },
                select: ['actor'],
                orderBy: [],
            } as any

            logic = personsModalLogic({
                query: mockActorsQuery,
                url: null,
            })
            logic.mount()

            // Simulate loaded actors with matched recordings
            const mockActors: PersonActorType[] = [
                {
                    type: 'person',
                    id: 'person-1',
                    distinct_ids: ['user-1'],
                    is_identified: true,
                    properties: {},
                    created_at: '2024-01-01',
                    matched_recordings: [
                        { session_id: 'session-1', events: [] },
                        { session_id: 'session-2', events: [] },
                    ],
                    value_at_data_point: null,
                },
                {
                    type: 'person',
                    id: 'person-2',
                    distinct_ids: ['user-2'],
                    is_identified: true,
                    properties: {},
                    created_at: '2024-01-01',
                    matched_recordings: [{ session_id: 'session-3', events: [] }],
                    value_at_data_point: null,
                },
                {
                    type: 'person',
                    id: 'person-3',
                    distinct_ids: ['user-3'],
                    is_identified: false,
                    properties: {},
                    created_at: '2024-01-01',
                    matched_recordings: [],
                    value_at_data_point: null,
                },
            ]

            logic.actions.loadActorsSuccess({
                results: [{ count: 3, people: mockActors }],
                missing_persons: 0,
            })

            expectLogic(logic).toMatchValues({
                sessionIdsFromLoadedActors: ['session-1', 'session-2', 'session-3'],
            })
        })

        it('returns empty array when actors have no matched_recordings', () => {
            const mockActorsQuery = {
                kind: NodeKind.ActorsQuery,
                source: {
                    kind: NodeKind.FunnelsActorsQuery,
                    source: {
                        kind: NodeKind.FunnelsQuery,
                        series: [],
                    },
                    funnelStep: -2,
                },
                select: ['actor'],
                orderBy: [],
            } as any

            logic = personsModalLogic({
                query: mockActorsQuery,
                url: null,
            })
            logic.mount()

            const mockActors: PersonActorType[] = [
                {
                    type: 'person',
                    id: 'person-1',
                    distinct_ids: ['user-1'],
                    is_identified: true,
                    properties: {},
                    created_at: '2024-01-01',
                    matched_recordings: [],
                    value_at_data_point: null,
                },
            ]

            logic.actions.loadActorsSuccess({
                results: [{ count: 1, people: mockActors }],
                missing_persons: 0,
            })

            expectLogic(logic).toMatchValues({
                sessionIdsFromLoadedActors: [],
            })
        })
    })

    describe('recordingFilters', () => {
        it('uses session IDs for InsightActorsQuery when available', () => {
            logic = personsModalLogic({
                query: {
                    kind: NodeKind.InsightActorsQuery,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                    },
                    includeRecordings: true,
                },
                url: '/api/environments/1/persons?',
                additionalSelect: { matched_recordings: 'matched_recordings' },
            })
            logic.mount()

            logic.actions.loadActorsSuccess({
                results: [
                    {
                        count: 1,
                        people: [
                            {
                                type: 'person',
                                id: 'person-1',
                                distinct_ids: ['user-1'],
                                is_identified: true,
                                properties: {},
                                created_at: '2024-01-01',
                                matched_recordings: [{ session_id: 'session-1', events: [] }],
                                value_at_data_point: null,
                            },
                        ],
                    },
                ],
                missing_persons: 0,
            })

            expectLogic(logic).toMatchValues({
                recordingFilters: {
                    session_ids: ['session-1'],
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [{ type: FilterLogicalOperator.And, values: [] }],
                    },
                    duration: [],
                },
            })
        })

        describe('funnel breakdown scoping', () => {
            const setupFunnelLogic = ({
                breakdownFilter,
                funnelStepBreakdown,
                matchedRecordings = [{ session_id: 'session-1', events: [] }],
            }: {
                breakdownFilter: FunnelsQuery['breakdownFilter']
                funnelStepBreakdown: FunnelsActorsQuery['funnelStepBreakdown']
                matchedRecordings?: Array<{ session_id: string; events: any[] }>
            }): void => {
                logic = personsModalLogic({
                    query: {
                        kind: NodeKind.FunnelsActorsQuery,
                        source: {
                            kind: NodeKind.FunnelsQuery,
                            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                            breakdownFilter,
                        },
                        funnelStep: 1,
                        funnelStepBreakdown,
                        includeRecordings: true,
                    },
                    url: '/api/environments/1/persons?',
                    additionalSelect: { matched_recordings: 'matched_recordings' },
                })
                logic.mount()
                logic.actions.loadActorsSuccess({
                    results: [
                        {
                            count: 1,
                            people: [
                                {
                                    type: 'person',
                                    id: 'person-1',
                                    distinct_ids: ['user-1'],
                                    is_identified: true,
                                    properties: {},
                                    created_at: '2024-01-01',
                                    matched_recordings: matchedRecordings,
                                    value_at_data_point: null,
                                },
                            ],
                        },
                    ],
                    missing_persons: 0,
                })
            }

            const expectSessionIdFilters = (innerFilters: unknown[]): void => {
                expectLogic(logic).toMatchValues({
                    recordingFilters: {
                        session_ids: ['session-1'],
                        filter_group: {
                            type: FilterLogicalOperator.And,
                            values: [{ type: FilterLogicalOperator.And, values: innerFilters }],
                        },
                        duration: [],
                    },
                })
            }

            it.each([
                {
                    scenario: 'event breakdown',
                    breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' as const },
                    funnelStepBreakdown: 'NL',
                    expectedFilter: {
                        key: '$geoip_country_code',
                        value: 'NL',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                },
                {
                    scenario: 'event breakdown with single-element array value (unwrapped)',
                    breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' as const },
                    funnelStepBreakdown: ['NL'],
                    expectedFilter: {
                        key: '$geoip_country_code',
                        value: 'NL',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                },
                {
                    scenario: 'person breakdown',
                    breakdownFilter: { breakdown: 'email', breakdown_type: 'person' as const },
                    funnelStepBreakdown: 'alice@example.com',
                    expectedFilter: {
                        key: 'email',
                        value: 'alice@example.com',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Person,
                    },
                },
                {
                    scenario: 'event_metadata breakdown',
                    breakdownFilter: { breakdown: '$session_id', breakdown_type: 'event_metadata' as const },
                    funnelStepBreakdown: 'session-abc',
                    expectedFilter: {
                        key: '$session_id',
                        value: 'session-abc',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.EventMetadata,
                    },
                },
                {
                    scenario: 'session breakdown',
                    breakdownFilter: {
                        breakdown: '$session_entry_referring_domain',
                        breakdown_type: 'session' as const,
                    },
                    funnelStepBreakdown: 'google.com',
                    expectedFilter: {
                        key: '$session_entry_referring_domain',
                        value: 'google.com',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Session,
                    },
                },
                {
                    scenario: 'group breakdown with group_type_index',
                    breakdownFilter: {
                        breakdown: 'company_name',
                        breakdown_type: 'group' as const,
                        breakdown_group_type_index: 0,
                    },
                    funnelStepBreakdown: 'Acme',
                    expectedFilter: {
                        key: 'company_name',
                        value: 'Acme',
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Group,
                        group_type_index: 0,
                    },
                },
                {
                    scenario: 'cohort breakdown',
                    breakdownFilter: { breakdown: [1, 2], breakdown_type: 'cohort' as const },
                    funnelStepBreakdown: 1,
                    expectedFilter: {
                        key: 'id',
                        value: 1,
                        operator: PropertyOperator.In,
                        type: PropertyFilterType.Cohort,
                    },
                },
            ])('emits a property filter for $scenario', ({ breakdownFilter, funnelStepBreakdown, expectedFilter }) => {
                setupFunnelLogic({ breakdownFilter, funnelStepBreakdown })
                expectSessionIdFilters([expectedFilter])
            })

            it.each([
                {
                    scenario: 'cohort breakdown with "all users" pseudo-cohort (0)',
                    breakdownFilter: { breakdown: [1, 2], breakdown_type: 'cohort' as const },
                    funnelStepBreakdown: 0,
                },
                {
                    scenario: 'cohort breakdown with "all" pseudo-cohort',
                    breakdownFilter: { breakdown: [1, 2], breakdown_type: 'cohort' as const },
                    funnelStepBreakdown: 'all',
                },
                {
                    scenario: 'cohort breakdown with non-numeric string value',
                    breakdownFilter: { breakdown: [1, 2], breakdown_type: 'cohort' as const },
                    funnelStepBreakdown: 'not-a-number',
                },
                {
                    scenario: 'group breakdown without breakdown_group_type_index',
                    breakdownFilter: { breakdown: 'company_name', breakdown_type: 'group' as const },
                    funnelStepBreakdown: 'Acme',
                },
                {
                    scenario: 'hogql breakdown',
                    breakdownFilter: { breakdown: 'toString(properties.foo)', breakdown_type: 'hogql' as const },
                    funnelStepBreakdown: 'bar',
                },
                {
                    scenario: 'data_warehouse breakdown',
                    breakdownFilter: {
                        breakdown: 'some_column',
                        breakdown_type: 'data_warehouse' as const,
                    },
                    funnelStepBreakdown: 'value',
                },
                {
                    scenario: 'multi-key breakdown property',
                    breakdownFilter: {
                        breakdown: ['$geoip_country_code', '$browser'],
                        breakdown_type: 'event' as const,
                    },
                    funnelStepBreakdown: 'NL',
                },
                {
                    scenario: 'multi-value breakdown array',
                    breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' as const },
                    funnelStepBreakdown: ['NL', 'BE'],
                },
            ])('bails out for $scenario', ({ breakdownFilter, funnelStepBreakdown }) => {
                setupFunnelLogic({ breakdownFilter, funnelStepBreakdown })
                expectSessionIdFilters([])
            })

            it('applies the filter in the fallback path when no session IDs are available', () => {
                setupFunnelLogic({
                    breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' },
                    funnelStepBreakdown: 'NL',
                    matchedRecordings: [],
                })
                const outerGroup = logic.values.recordingFilters.filter_group
                const innerGroup = outerGroup?.values?.[0]
                const innerValues = innerGroup && 'values' in innerGroup ? innerGroup.values : []
                expect(innerValues).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            key: '$geoip_country_code',
                            value: 'NL',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        }),
                    ])
                )
            })
        })

        it('falls back to event filters when no session IDs are available', () => {
            logic = personsModalLogic({
                query: {
                    kind: NodeKind.InsightActorsQuery,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            { kind: NodeKind.EventsNode, event: '$pageview' },
                            { kind: NodeKind.EventsNode, event: 'sign_up' },
                        ],
                    },
                    includeRecordings: true,
                },
                url: '/api/environments/1/persons?',
                additionalSelect: { matched_recordings: 'matched_recordings' },
            })
            logic.mount()

            logic.actions.loadActorsSuccess({
                results: [
                    {
                        count: 1,
                        people: [
                            {
                                type: 'person',
                                id: 'person-1',
                                distinct_ids: ['user-1'],
                                is_identified: true,
                                properties: {},
                                created_at: '2024-01-01',
                                matched_recordings: [],
                                value_at_data_point: null,
                            },
                        ],
                    },
                ],
                missing_persons: 0,
            })

            const filters = logic.values.recordingFilters
            const innerValues = (filters.filter_group as any)?.values?.[0]?.values
            expect(innerValues).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ id: '$pageview', type: 'events' }),
                    expect.objectContaining({ id: 'sign_up', type: 'events' }),
                ])
            )
        })
    })
})
