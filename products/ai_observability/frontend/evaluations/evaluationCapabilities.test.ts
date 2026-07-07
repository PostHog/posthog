import { FEATURE_FLAGS } from 'lib/constants'

import { evaluationSupportsReports, evaluationTypeCanBeCreated } from './evaluationCapabilities'

describe('evaluationCapabilities', () => {
    it('gates sentiment creation on the sentiment evaluations feature flag', () => {
        expect(evaluationTypeCanBeCreated('llm_judge', {})).toBe(true)
        expect(evaluationTypeCanBeCreated('hog', {})).toBe(true)
        expect(evaluationTypeCanBeCreated('sentiment', {})).toBe(false)
        expect(
            evaluationTypeCanBeCreated('sentiment', {
                [FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_SENTIMENT]: true,
            })
        ).toBe(true)
    })

    it('supports reports only for boolean generation-target evaluations', () => {
        expect(evaluationSupportsReports({ output_type: 'boolean', target: 'generation' })).toBe(true)
        expect(evaluationSupportsReports({ output_type: 'boolean', target: 'trace' })).toBe(false)
        expect(evaluationSupportsReports({ output_type: 'sentiment', target: 'generation' })).toBe(false)
    })
})
