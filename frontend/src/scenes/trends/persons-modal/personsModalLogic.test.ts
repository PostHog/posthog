import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PersonActorType } from '~/types'

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
                } as any,
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
                } as any,
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
