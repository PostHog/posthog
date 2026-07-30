import { dateGrainOptionsForField } from './builderLabels'

describe('builderLabels', () => {
    describe('dateGrainOptionsForField', () => {
        it.each([
            // [typeName, includesHour] — hour bucketing on a DATE column is a no-op
            ['DATE', false],
            ['DATETIME', true],
            [undefined, true], // pill whose field is no longer in the base query
        ])('%s → offers hour: %s', (typeName, includesHour) => {
            const options = dateGrainOptionsForField(typeName ? { typeName } : undefined)
            expect(options.includes('hour')).toEqual(includesHour)
            expect(options).toContain('day')
            expect(options).toContain('year')
        })
    })
})
