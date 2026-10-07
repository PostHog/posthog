import { modelQuality } from './modelQuality'

describe('modelQuality', () => {
    const base = { holdoutAuc: null, realizedAuc: null, liftAt10: null, isPreliminary: false, target: 'signed_up' }

    test.each([
        {
            name: 'realized AUC wins over holdout AUC',
            input: { holdoutAuc: 0.9, realizedAuc: 0.65, liftAt10: 1.24 },
            expected: {
                verdict: 'Weak',
                basis: 'confirmed',
                auc: 0.65,
                sentence: 'Top 10% are 1.2× more likely to do signed_up',
            },
        },
        {
            name: '0.80 is strong',
            input: { realizedAuc: 0.8, liftAt10: 3.4 },
            expected: {
                verdict: 'Strong',
                basis: 'confirmed',
                auc: 0.8,
                sentence: 'Top 10% are 3.4× more likely to do signed_up',
            },
        },
        {
            name: 'just under 0.80 is fair',
            input: { holdoutAuc: 0.7999 },
            expected: {
                verdict: 'Fair',
                basis: 'testing only',
                auc: 0.7999,
                sentence: 'Not checked against real outcomes yet',
            },
        },
        {
            name: '0.70 is fair',
            input: { holdoutAuc: 0.7 },
            expected: {
                verdict: 'Fair',
                basis: 'testing only',
                auc: 0.7,
                sentence: 'Not checked against real outcomes yet',
            },
        },
        {
            name: 'just under 0.70 is weak',
            input: { holdoutAuc: 0.6999 },
            expected: {
                verdict: 'Weak',
                basis: 'testing only',
                auc: 0.6999,
                sentence: 'Not checked against real outcomes yet',
            },
        },
        {
            name: 'a preliminary champion uses holdout AUC',
            input: { holdoutAuc: 0.82, realizedAuc: 0.6, isPreliminary: true },
            expected: {
                verdict: 'Strong',
                basis: 'testing only',
                auc: 0.82,
                sentence: 'Not checked against real outcomes yet',
            },
        },
        {
            name: 'a confirmed model with no lift had no one do the target',
            input: { realizedAuc: 0.78 },
            expected: {
                verdict: 'Fair',
                basis: 'confirmed',
                auc: 0.78,
                sentence: 'No one did signed_up in the latest check',
            },
        },
        { name: 'no AUC gives no verdict', input: {}, expected: null },
    ])('$name', ({ input, expected }) => {
        expect(modelQuality({ ...base, ...input })).toEqual(expected)
    })
})
