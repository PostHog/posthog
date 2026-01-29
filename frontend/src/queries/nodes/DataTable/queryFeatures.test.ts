import { NodeKind } from '~/queries/schema/schema-general'

import { QueryFeature, getQueryFeatures } from './queryFeatures'

describe('getQueryFeatures', () => {
    describe('displayResponseError', () => {
        it.each([
            [NodeKind.GroupsQuery, { kind: NodeKind.GroupsQuery, group_type_index: 0 }],
            [NodeKind.ActorsQuery, { kind: NodeKind.ActorsQuery }],
            [NodeKind.TracesQuery, { kind: NodeKind.TracesQuery }],
            [NodeKind.EventsQuery, { kind: NodeKind.EventsQuery, select: ['*'] }],
            [NodeKind.SessionsQuery, { kind: NodeKind.SessionsQuery }],
            [NodeKind.HogQLQuery, { kind: NodeKind.HogQLQuery, query: 'SELECT 1' }],
        ])('%s should have displayResponseError enabled', (_, query) => {
            const features = getQueryFeatures(query)
            expect(features.has(QueryFeature.displayResponseError)).toBe(true)
        })
    })

    describe('columnConfigurator with displayResponseError', () => {
        it.each([
            [NodeKind.GroupsQuery, { kind: NodeKind.GroupsQuery, group_type_index: 0 }],
            [NodeKind.ActorsQuery, { kind: NodeKind.ActorsQuery }],
            [NodeKind.TracesQuery, { kind: NodeKind.TracesQuery }],
            [NodeKind.EventsQuery, { kind: NodeKind.EventsQuery, select: ['*'] }],
            [NodeKind.SessionsQuery, { kind: NodeKind.SessionsQuery }],
        ])('%s with columnConfigurator should also have displayResponseError', (_, query) => {
            const features = getQueryFeatures(query)
            if (features.has(QueryFeature.columnConfigurator)) {
                expect(features.has(QueryFeature.displayResponseError)).toBe(true)
            }
        })
    })
})
