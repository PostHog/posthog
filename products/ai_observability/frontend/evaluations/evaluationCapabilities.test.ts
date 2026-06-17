import { FEATURE_FLAGS } from 'lib/constants'

import { evaluationTypeCanBeCreated } from './evaluationCapabilities'

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
})
