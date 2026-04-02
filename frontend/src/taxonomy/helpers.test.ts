import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { getCoreFilterDefinition } from './helpers'

describe('getCoreFilterDefinition', () => {
    const type = TaxonomicFilterGroupType.EventProperties

    describe('$survey_response_ prefix', () => {
        it.each([
            [
                '$survey_response_0',
                'Survey response for 1th question',
                'The response value for the 1th question in the survey.',
            ],
            [
                '$survey_response_1',
                'Survey response for 2nd question',
                'The response value for the 2nd question in the survey.',
            ],
            [
                '$survey_response_2',
                'Survey response for 3rd question',
                'The response value for the 3rd question in the survey.',
            ],
            [
                '$survey_response_3',
                'Survey response for 4th question',
                'The response value for the 4th question in the survey.',
            ],
        ])('returns ordinal label for %s', (key, label, description) => {
            expect(getCoreFilterDefinition(key, type)).toEqual({ label, description })
        })

        it.each([
            [
                '$survey_response_abc123-def4-5678',
                'Survey response (abc123-def4-5678)',
                'The response value for survey question with ID: "abc123-def4-5678".',
            ],
            ['$survey_response_q1', 'Survey response (q1)', 'The response value for survey question with ID: "q1".'],
        ])('returns fallback label for non-numeric key %s', (key, label, description) => {
            expect(getCoreFilterDefinition(key, type)).toEqual({ label, description })
        })

        it('returns core definition for bare $survey_response without suffix', () => {
            const result = getCoreFilterDefinition('$survey_response', type)
            expect(result).not.toBeNull()
            expect(result!.label).toBe('Survey response')
        })
    })

    it('returns null for null/undefined values', () => {
        expect(getCoreFilterDefinition(null, type)).toBeNull()
        expect(getCoreFilterDefinition(undefined, type)).toBeNull()
    })
})
