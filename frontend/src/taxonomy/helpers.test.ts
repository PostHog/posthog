import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { getCoreFilterDefinition } from './helpers'

describe('getCoreFilterDefinition', () => {
    describe('$survey_response_<index>', () => {
        it.each([
            [0, '1st'],
            [1, '2nd'],
            [2, '3rd'],
            [3, '4th'],
            [10, '11th'],
            [11, '12th'],
            [12, '13th'],
            [20, '21st'],
            [21, '22nd'],
            [22, '23rd'],
            [110, '111th'],
        ])('formats index %d as %s', (index, expectedOrdinal) => {
            const result = getCoreFilterDefinition(
                `$survey_response_${index}`,
                TaxonomicFilterGroupType.EventProperties
            )
            expect(result?.label).toBe(`Survey response for ${expectedOrdinal} question`)
            expect(result?.description).toBe(
                `The response value for the ${expectedOrdinal} question in the survey.`
            )
        })
    })

    describe('$survey_response_<uuid> (id-based key)', () => {
        it('produces a label that includes the question id, not "NaNth"', () => {
            const id = '019db675-8574-0000-7bcd-8b96a8c4437d'
            const result = getCoreFilterDefinition(
                `$survey_response_${id}`,
                TaxonomicFilterGroupType.EventProperties
            )
            expect(result?.label).toBe(`Survey response for question ${id}`)
            expect(result?.label).not.toMatch(/NaN/)
            expect(result?.description).toContain(id)
        })

        it('handles non-uuid alphanumeric ids', () => {
            const result = getCoreFilterDefinition(
                '$survey_response_question-abc',
                TaxonomicFilterGroupType.EventProperties
            )
            expect(result?.label).toBe('Survey response for question question-abc')
            expect(result?.label).not.toMatch(/NaN/)
        })
    })

    describe('edge cases', () => {
        it('returns null for `$survey_response_` with empty suffix', () => {
            const result = getCoreFilterDefinition(
                '$survey_response_',
                TaxonomicFilterGroupType.EventProperties
            )
            expect(result).toBeNull()
        })
    })
})
