import { metricStarterQuery } from './metricStarterChecks'

describe('metricStarterQuery', () => {
    it('quotes metric columns whose names are not plain identifiers', () => {
        const query = metricStarterQuery('no_sharp_drop', [
            { name: 'event day', type: 'Nullable(Date)' },
            { name: 'signups.total', type: 'UInt64' },
        ])

        expect(query).toContain('lagInFrame("signups.total") OVER (ORDER BY "event day")')
        expect(query).toContain('AND "signups.total" < previous_value * 0.5')
    })

    it('escapes a column name that already looks quoted instead of passing it through', () => {
        const query = metricStarterQuery('value_in_range', [{ name: '"value" + 1 + "value"', type: 'UInt64' }])

        expect(query).toEqual(
            'SELECT *\nFROM {metric}\nWHERE `"value" + 1 + "value"` < 0 OR `"value" + 1 + "value"` > 1000000'
        )
    })
})
