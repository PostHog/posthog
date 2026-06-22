import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { getCoreFilterDefinition } from './helpers'

describe('getCoreFilterDefinition', () => {
    describe('$survey_response_<index> ordinal labels', () => {
        // suffix is the 0-indexed question index, the label shows the 1-indexed ordinal
        it.each([
            { suffix: '0', ordinal: '1st' },
            { suffix: '1', ordinal: '2nd' },
            { suffix: '2', ordinal: '3rd' },
            { suffix: '3', ordinal: '4th' },
            { suffix: '9', ordinal: '10th' },
            { suffix: '10', ordinal: '11th' },
            { suffix: '11', ordinal: '12th' },
            { suffix: '12', ordinal: '13th' },
            { suffix: '20', ordinal: '21st' },
            { suffix: '21', ordinal: '22nd' },
            { suffix: '22', ordinal: '23rd' },
            { suffix: '99', ordinal: '100th' },
            { suffix: '100', ordinal: '101st' },
            { suffix: '110', ordinal: '111th' },
        ])('labels question index $suffix as the $ordinal question', ({ suffix, ordinal }) => {
            const definition = getCoreFilterDefinition(
                `$survey_response_${suffix}`,
                TaxonomicFilterGroupType.EventProperties
            )
            expect(definition?.label).toBe(`Survey response for ${ordinal} question`)
            expect(definition?.description).toBe(`The response value for the ${ordinal} question in the survey.`)
        })
    })

    it('does not render an id-based response key as a "NaNth question"', () => {
        const definition = getCoreFilterDefinition(
            '$survey_response_018f1234-5678-0000-abcd-000000000000',
            TaxonomicFilterGroupType.EventProperties
        )
        expect(definition?.label).not.toContain('NaN')
        expect(definition?.label).toBe('Survey response (018f1234…)')
    })
})
