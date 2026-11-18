import { EMPTY_UTM_LABEL, MappableColumn, getMappableColumn, isMappableValue, withEmptyUtmLabel } from './mappingUtils'

describe('mappingUtils', () => {
    describe('getMappableColumn', () => {
        it.each([
            ['Campaign', MappableColumn.Campaign],
            ['Source', MappableColumn.Source],
            ['source', MappableColumn.Source],
            ['Cost', null],
            ['Ad group', null],
        ])('maps column %s to %s', (columnName, expected) => {
            expect(getMappableColumn(columnName)).toBe(expected)
        })
    })

    describe('isMappableValue', () => {
        it.each([
            ['newsletter', true],
            ['fall_sale', true],
            // A saved mapping for the organic label would rewrite every untagged session as that
            // ad platform, so the menu must never offer it.
            ['organic', false],
            ['Organic', false],
            ['', false],
            [null, false],
            [undefined, false],
        ])('treats %s as mappable: %s', (value, expected) => {
            expect(isMappableValue(value)).toBe(expected)
        })
    })

    describe('withEmptyUtmLabel', () => {
        it.each([
            ['Campaign', 'organic', EMPTY_UTM_LABEL],
            ['Source', 'organic', EMPTY_UTM_LABEL],
            ['Source', 'Organic', EMPTY_UTM_LABEL],
            ['Campaign', 'summer_sale', 'summer_sale'],
            ['Source', 'google', 'google'],
        ])('column %s with value %s shows %s', (key, value, expected) => {
            expect(withEmptyUtmLabel({ key, value }).value).toBe(expected)
        })

        it('leaves a column that is not campaign or source alone', () => {
            expect(withEmptyUtmLabel({ key: 'Channel', value: 'organic' }).value).toBe('organic')
        })

        it('returns the same object when nothing changes, so a cell does not re-render', () => {
            const item = { key: 'Campaign', value: 'summer_sale' }
            expect(withEmptyUtmLabel(item)).toBe(item)
        })
    })
})
