import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { activeColumnView, columnsForView, withoutDefaultPins } from './marketingTableColumnViews'

const defaultColumns = [
    'Campaign',
    'ID',
    'Source',
    'Cost',
    'Clicks',
    'Impressions',
    'CPC',
    'CTR',
    'Reported Conversions',
    'Reported Conversion Value',
    'Reported ROAS',
    'Cost per Reported Conversions',
    'Trial started',
    'Cost per Trial started',
]

describe('marketing table column views', () => {
    it.each([
        ['default', ['Campaign', 'ID', 'Source', 'Cost', 'Clicks', 'CTR', 'Reported Conversions', 'Trial started']],
        ['clicks', ['Campaign', 'ID', 'Source', 'Cost', 'Clicks', 'Impressions', 'CPC', 'CTR']],
        [
            'conversions',
            [
                'Campaign',
                'ID',
                'Source',
                'Cost',
                'Reported Conversions',
                'Reported Conversion Value',
                'Reported ROAS',
                'Cost per Reported Conversions',
                'Trial started',
                'Cost per Trial started',
            ],
        ],
    ] as const)('keeps breakdown columns first for the %s view and recognizes it again', (view, expected) => {
        expect(columnsForView(view, defaultColumns)).toEqual(expected)
        expect(activeColumnView(columnsForView(view, defaultColumns), defaultColumns)).toBe(view)
    })

    it('treats hand-picked columns as a custom view', () => {
        expect(activeColumnView(['Campaign', 'Cost'], defaultColumns)).toBeNull()
        expect(activeColumnView(undefined, defaultColumns)).toBe('default')
    })

    it('keeps a goal named like a cost in the default view', () => {
        expect(columnsForView('default', ['Campaign', 'Cost per lead', 'Cost per Cost per lead'])).toEqual([
            'Campaign',
            'Cost per lead',
        ])
    })

    it.each([
        ['drops pins that match the breakdown columns', ['Source', 'Campaign'], undefined],
        ['keeps pins someone chose', ['Campaign', 'Cost'], ['Campaign', 'Cost']],
    ])('%s', (_, pinnedColumns, expected) => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            pinnedColumns,
            source: {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['Campaign', 'Source', 'Cost'],
            },
        }
        expect(withoutDefaultPins(query).pinnedColumns).toEqual(expected)
    })
})
