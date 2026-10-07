import { liftSentence, modelQuality } from './modelQuality'

describe('modelQuality', () => {
    test.each([
        { holdout: 0.9, realized: 0.65, expected: { level: 'weak', auc: 0.65, source: 'realized' } },
        { holdout: 0.8, realized: null, expected: { level: 'strong', auc: 0.8, source: 'holdout' } },
        { holdout: 0.7999, realized: undefined, expected: { level: 'fair', auc: 0.7999, source: 'holdout' } },
        { holdout: null, realized: 0.7, expected: { level: 'fair', auc: 0.7, source: 'realized' } },
        { holdout: 0.6999, realized: null, expected: { level: 'weak', auc: 0.6999, source: 'holdout' } },
        { holdout: null, realized: null, expected: null },
    ])('holdout $holdout and realized $realized', ({ holdout, realized, expected }) => {
        expect(modelQuality(holdout, realized)).toEqual(expected)
    })

    test.each([
        { lift: 2.44, expected: 'The top 10% of people by score did the target 2.4x as often as average.' },
        { lift: null, expected: null },
    ])('lift sentence for $lift', ({ lift, expected }) => {
        expect(liftSentence(lift)).toEqual(expected)
    })
})
