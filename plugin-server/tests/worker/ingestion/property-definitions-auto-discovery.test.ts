import { PropertyType } from '../../../src/types'
import { detectPropertyDefinitionTypes } from '../../../src/worker/ingestion/property-definitions-auto-discovery'

describe('property definitions auto discovery', () => {
    describe('can detect numbers', () => {
        it('can detect "10"', () => {
            expect(detectPropertyDefinitionTypes('10', 'anything')).toEqual(PropertyType.Numeric)
        })

        it('can detect 10', () => {
            expect(detectPropertyDefinitionTypes(10, 'anything')).toEqual(PropertyType.Numeric)
        })

        it('can detect ""', () => {
            expect(detectPropertyDefinitionTypes('', 'anything')).toEqual(PropertyType.String)
        })

        it('can detect null', () => {
            expect(detectPropertyDefinitionTypes(null, 'anything')).toEqual(null)
        })

        it('can detect decimals', () => {
            expect(detectPropertyDefinitionTypes(1.23, 'anything')).toEqual(PropertyType.Numeric)
        })

        it('can detect decimals in strings', () => {
            expect(detectPropertyDefinitionTypes('1.23', 'anything')).toEqual(PropertyType.Numeric)
        })

        it('can detect booleans', () => {
            expect(detectPropertyDefinitionTypes(true, 'anything')).toEqual(PropertyType.Boolean)
            expect(detectPropertyDefinitionTypes(false, 'anything')).toEqual(PropertyType.Boolean)
        })

        it('can detect booleans in strings', () => {
            expect(detectPropertyDefinitionTypes('true', 'anything')).toEqual(PropertyType.Boolean)
            expect(detectPropertyDefinitionTypes('false', 'anything')).toEqual(PropertyType.Boolean)
            expect(detectPropertyDefinitionTypes('False', 'anything')).toEqual(PropertyType.Boolean)
            expect(detectPropertyDefinitionTypes('True', 'anything')).toEqual(PropertyType.Boolean)
        })
    })
})
