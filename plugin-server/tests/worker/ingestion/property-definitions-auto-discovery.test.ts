import { PropertyType } from '../../../src/types'
import { detectPropertyDefinitionTypes } from '../../../src/worker/ingestion/property-definitions-auto-discovery'

describe('property definitions auto discovery', () => {
    describe('can detect numbers', () => {
        it('can detect "10"', () => {
            expect(detectPropertyDefinitionTypes('10', 'anything')).toEqual(PropertyType.String)
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

        it('can detect version numbers as non numeric', () => {
            expect(detectPropertyDefinitionTypes('1.2.3', 'anything')).toEqual(PropertyType.String)
            expect(detectPropertyDefinitionTypes('9.7.0', '$app_version')).toEqual(PropertyType.String)
        })
    })

    describe('can detect feature flag properties', () => {
        it('detects regular feature flag properties as string', () => {
            expect(detectPropertyDefinitionTypes('10', '$feature/my-feature')).toEqual(PropertyType.String)
            expect(detectPropertyDefinitionTypes('true', '$feature/my-feature')).toEqual(PropertyType.String)
            expect(detectPropertyDefinitionTypes('false', '$feature/my-feature')).toEqual(PropertyType.String)
            expect(detectPropertyDefinitionTypes(12, '$feature/my-feature')).toEqual(PropertyType.String)
        })

        it('doesnt detect $feature_interaction properties as string', () => {
            expect(detectPropertyDefinitionTypes('true', '$feature_interaction/my-feature')).toEqual(
                PropertyType.Boolean
            )
            expect(detectPropertyDefinitionTypes('true', '$$feature/my-feature')).toEqual(PropertyType.Boolean)
            expect(detectPropertyDefinitionTypes('true', ' $feature/my-feature')).toEqual(PropertyType.Boolean)
            expect(detectPropertyDefinitionTypes('true', '$feat/$feature/my-feature')).toEqual(PropertyType.Boolean)
            expect(detectPropertyDefinitionTypes('true', '$features/my-feature')).toEqual(PropertyType.Boolean)
            expect(detectPropertyDefinitionTypes('["a","b","c"]', '$active_feature_flags')).toEqual(PropertyType.String)
            expect(detectPropertyDefinitionTypes(12, 'feature_flag')).toEqual(PropertyType.Numeric)
        })
    })

    describe('can detect $feature_flag_response properties', () => {
        it('detects regular feature flag response properties as string', () => {
            expect(detectPropertyDefinitionTypes('10', '$feature_flag_response')).toEqual(PropertyType.String)
            expect(detectPropertyDefinitionTypes('true', '$feature_flag_response')).toEqual(PropertyType.String)
            expect(detectPropertyDefinitionTypes('false', '$feature_flag_response')).toEqual(PropertyType.String)
            expect(detectPropertyDefinitionTypes(12, '$feature_flag_response')).toEqual(PropertyType.String)
        })
    })
})
