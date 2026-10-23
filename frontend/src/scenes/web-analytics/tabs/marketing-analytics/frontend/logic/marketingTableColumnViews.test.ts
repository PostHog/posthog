import { activeColumnView, columnsForView } from './marketingTableColumnViews'

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
})
