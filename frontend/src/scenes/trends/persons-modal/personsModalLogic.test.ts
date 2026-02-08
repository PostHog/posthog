import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PersonActorType } from '~/types'

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
})
