import { dayjs } from 'lib/dayjs'

import { TrendsQuery } from '~/queries/schema/schema-general'
import { PropertyType } from '~/types'

import { SchemaPropertyGroupProperty } from '../schema/schemaManagementLogic'
import { buildPropertyGroupTrendsQuery } from './propertyGroupTrendsQuery'

describe('buildPropertyGroupTrendsQuery', () => {
    const properties: SchemaPropertyGroupProperty[] = [
        {
            id: '1',
            name: 'plan',
            property_type: PropertyType.String,
            is_required: true,
            is_optional_in_types: false,
            description: '',
        },
        {
            id: '2',
            name: 'price',
            property_type: PropertyType.Numeric,
            is_required: false,
            is_optional_in_types: false,
            description: '',
        },
    ]

    const sourceOf = (...args: Parameters<typeof buildPropertyGroupTrendsQuery>): TrendsQuery =>
        buildPropertyGroupTrendsQuery(...args).query.source as TrendsQuery

    it('builds one coverage formula (propertyCount / eventCount) per property', () => {
        const source = sourceOf('purchase', properties)

        // Base count series A, then one is_set series per property (B, C, …).
        expect(source.series).toHaveLength(3)
        expect(source.series[0]).toMatchObject({ event: 'purchase', math: 'total' })
        expect(source.series[1]).toMatchObject({
            event: 'purchase',
            properties: [{ key: 'plan', operator: 'is_set' }],
        })
        expect(source.trendsFilter?.formulaNodes).toEqual([
            { formula: 'B/A * 100', custom_name: 'plan' },
            { formula: 'C/A * 100', custom_name: 'price' },
        ])
        expect(source.trendsFilter?.aggregationAxisFormat).toBe('percentage')
    })

    it('truncates to 25 properties so series labels stay within B–Z', () => {
        const many = Array.from({ length: 30 }, (_, i) => ({ ...properties[0], id: String(i), name: `p${i}` }))
        const result = buildPropertyGroupTrendsQuery('e', many)

        expect(result.isTruncated).toBe(true)
        expect(result.totalProperties).toBe(30)
        expect(result.displayedProperties).toBe(25)
        expect((result.query.source as TrendsQuery).series).toHaveLength(26) // base + 25
    })

    // The bug this guards: weeks before the event existed evaluate coverage as 0/0 → 0%, painting a
    // flat 0% line across the whole window. Clamping the start to the event's first-seen removes them.
    it('clamps the window to first-seen for an event younger than 90 days', () => {
        const firstSeen = dayjs().subtract(10, 'day').toISOString()
        const result = buildPropertyGroupTrendsQuery('e', properties, firstSeen)

        expect((result.query.source as TrendsQuery).dateRange?.date_from).toBe(dayjs(firstSeen).format('YYYY-MM-DD'))
        expect(result.dateRangeLabel).toBe(`since ${dayjs(firstSeen).format('MMM D, YYYY')}`)
    })

    it.each([
        ['first-seen is older than the window', dayjs().subtract(200, 'day').toISOString()],
        ['first-seen is unknown', undefined],
        ['first-seen is unparseable', 'not-a-date'],
    ])('keeps the default 90-day window when %s', (_label, firstSeen) => {
        const result = buildPropertyGroupTrendsQuery('e', properties, firstSeen)

        expect((result.query.source as TrendsQuery).dateRange?.date_from).toBe('-90d')
        expect(result.dateRangeLabel).toBe('last 90 days')
    })
})
