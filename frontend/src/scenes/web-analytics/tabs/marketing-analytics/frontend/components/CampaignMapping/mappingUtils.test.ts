import { MappableColumn, getMappableColumn, isMappableValue } from './mappingUtils'

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
})
