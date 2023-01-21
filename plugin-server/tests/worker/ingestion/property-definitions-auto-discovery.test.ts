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

        it('can detect version numbers as non numeric', () => {
            expect(detectPropertyDefinitionTypes('1.2.3', 'anything')).toEqual(PropertyType.String)
            expect(detectPropertyDefinitionTypes('9.7.0', '$app_version')).toEqual(PropertyType.String)
        })
    })
})
