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
})
