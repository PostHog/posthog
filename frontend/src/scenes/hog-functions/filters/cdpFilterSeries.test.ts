import { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { NodeKind } from '~/queries/schema/schema-general'

import { CdpFilterEntities, cdpFiltersToSeries, seriesToCdpFilters } from './cdpFilterSeries'

const exampleUrl = { key: '$current_url', value: 'https://example.com', operator: 'icontains', type: 'event' }

describe('cdpFilterSeries', () => {
    test.each<[string, Partial<CdpFilterEntities>, CdpFilterEntities]>([
        [
            'events, actions and warehouse tables keep their fields and come back sorted by order',
            {
                events: [{ id: '$pageview', type: 'events', name: '$pageview', order: 0, properties: [exampleUrl] }],
                actions: [{ id: '9', type: 'actions', name: 'Users signed up', order: 1, properties: [] }],
                data_warehouse: [
                    {
                        id: 'payments',
                        type: 'data_warehouse',
                        name: 'payments',
                        order: 2,
                        uuid: '0189e1f0-0000-0000-0000-000000000000',
                        table_name: 'payments',
                        timestamp_field: 'created_at',
                        distinct_id_field: 'person_id',
                        id_field: 'id',
                        properties: [],
                    },
                ],
            },
            {
                actions: [{ name: 'Users signed up', properties: [], id: 9, type: 'actions', order: 1 }],
                events: [{ name: '$pageview', properties: [exampleUrl], id: '$pageview', type: 'events', order: 0 }],
                data_warehouse: [
                    {
                        name: 'payments',
                        table_name: 'payments',
                        timestamp_field: 'created_at',
                        distinct_id_field: 'person_id',
                        id_field: 'id',
                        properties: [],
                        id: 'payments',
                        type: 'data_warehouse',
                        order: 2,
                    },
                ],
                groups: [],
            },
        ],
        [
            'custom names stay and gaps in order close up',
            {
                events: [
                    { id: 'purchased', type: 'events', name: 'purchased', custom_name: 'Checkout', order: 7 },
                    { id: '$pageview', type: 'events', name: '$pageview', order: 3 },
                ],
            },
            {
                actions: [],
                events: [
                    { name: '$pageview', id: '$pageview', type: 'events', order: 0 },
                    { name: 'purchased', custom_name: 'Checkout', id: 'purchased', type: 'events', order: 1 },
                ],
                data_warehouse: [],
                groups: [],
            },
        ],
        [
            'a group keeps its operator and nested event and action',
            {
                groups: [
                    {
                        type: 'groups',
                        name: 'Signed up or purchased',
                        operator: 'OR',
                        order: 0,
                        nestedFilters: [
                            { id: 'signed_up', type: 'events', name: 'signed_up', order: 0 },
                            { id: '12', type: 'actions', name: 'Purchased', order: 1, properties: [exampleUrl] },
                        ],
                    },
                ],
            },
            {
                actions: [],
                events: [],
                data_warehouse: [],
                groups: [
                    {
                        name: 'Signed up or purchased',
                        operator: 'OR',
                        nestedFilters: [
                            { name: 'signed_up', id: 'signed_up', type: 'events', order: 0 },
                            { name: 'Purchased', properties: [exampleUrl], id: 12, type: 'actions', order: 1 },
                        ],
                        id: null,
                        type: 'groups',
                        order: 0,
                    },
                ],
            },
        ],
    ])('%s', (_, stored, expected) => {
        expect(JSON.stringify(seriesToCdpFilters(cdpFiltersToSeries(stored)))).toEqual(JSON.stringify(expected))
    })

    test('a row the picker built drops its node version', () => {
        const series = [{ kind: NodeKind.ActionsNode, id: 4, name: 'Clicked buy', version: 1 } as SeriesNode]
        expect(JSON.stringify(seriesToCdpFilters(series).actions)).toEqual(
            JSON.stringify([{ name: 'Clicked buy', id: 4, type: 'actions', order: 0 }])
        )
    })
})
