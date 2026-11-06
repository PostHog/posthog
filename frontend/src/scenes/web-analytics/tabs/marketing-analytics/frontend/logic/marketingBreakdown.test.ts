import { BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import { displayBreakdownValue } from './marketingBreakdown'

describe('marketingBreakdown', () => {
    it('names the folded row instead of printing the sentinel the backend folds into', () => {
        // The backend rolls the long tail into a sentinel string. Rendering it raw puts
        // "$$_posthog_breakdown_other_$$" in the table while the caveat text below talks about "Other".
        expect(displayBreakdownValue(BREAKDOWN_OTHER_STRING_LABEL, 'Channel')).toBe('Other')
    })

    it('names the dimension when a session carried no value for it', () => {
        expect(displayBreakdownValue('', 'Referring domain')).toBe('(no referring domain)')
    })

    it('passes a real value through untouched', () => {
        expect(displayBreakdownValue('google', 'Source')).toBe('google')
    })
})
