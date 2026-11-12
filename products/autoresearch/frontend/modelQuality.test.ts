import { FeatureDirectionEnumApi, FeatureImportanceApi } from './generated/api.schemas'
import { dominantDriver, formatAuc, isLiftAtCeiling, modelQuality } from './modelQuality'

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
                sentence: 'Top 10% are 1.2× more likely to do “signed_up”',
            },
        },
        {
            name: '0.80 is strong',
            input: { realizedAuc: 0.8, liftAt10: 3.4 },
            expected: {
                verdict: 'Strong',
                basis: 'confirmed',
                auc: 0.8,
                sentence: 'Top 10% are 3.4× more likely to do “signed_up”',
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
                sentence: 'No one did “signed_up” in the latest check',
            },
        },
        {
            name: 'a lift at the top 10% ceiling says nearly everyone was in the top 10%',
            input: { realizedAuc: 0.996, liftAt10: 9.78 },
            expected: {
                verdict: 'Strong',
                basis: 'confirmed',
                auc: 0.996,
                sentence: 'Nearly everyone who did “signed_up” was in the top 10%',
            },
        },
        { name: 'no AUC gives no verdict', input: {}, expected: null },
    ])('$name', ({ input, expected }) => {
        expect(modelQuality({ ...base, ...input })).toEqual(expected)
    })
})

describe('formatAuc', () => {
    test.each([
        [0.7, '0.70'],
        [0.994, '0.99'],
        [0.995, '0.995'],
        [0.996, '0.996'],
        [0.9996, '0.999'],
        [1, '1.00'],
    ])('%s shows as %s', (auc, expected) => {
        expect(formatAuc(auc)).toEqual(expected)
    })
})

describe('isLiftAtCeiling', () => {
    test.each([
        { name: '9.78 at the top 10%', lift: 9.78, share: 0.1, baseRate: 0.02, expected: true },
        { name: '4.94 at the top 20%', lift: 4.94, share: 0.2, baseRate: 0.02, expected: true },
        { name: '3.4 at the top 10%', lift: 3.4, share: 0.1, baseRate: 0.02, expected: false },
        { name: '4.0 at the top 20%', lift: 4.0, share: 0.2, baseRate: 0.02, expected: false },
        { name: '2.45 at the top 10% with a 40% base rate', lift: 2.45, share: 0.1, baseRate: 0.4, expected: true },
        { name: '9.78 at the top 10% with no base rate', lift: 9.78, share: 0.1, baseRate: null, expected: true },
    ])('$name is $expected', ({ lift, share, baseRate, expected }) => {
        expect(isLiftAtCeiling(lift, share, baseRate)).toEqual(expected)
    })
})

describe('dominantDriver', () => {
    const feature = (name: string, importance: number): FeatureImportanceApi => ({
        name,
        importance,
        direction: FeatureDirectionEnumApi.Positive,
    })

    test.each([
        { name: 'exactly the ratio', importances: [0.75, 0.25, 0.05], expected: 'f0' },
        { name: 'above the ratio', importances: [0.76, 0.25], expected: 'f0' },
        { name: 'just under the ratio', importances: [0.74, 0.25], expected: null },
        { name: 'features out of order', importances: [0.1, 0.4], expected: 'f1' },
        { name: 'a second feature with no importance', importances: [0.2, 0], expected: 'f0' },
        { name: 'one feature', importances: [0.2], expected: null },
        { name: 'no importance at all', importances: [0, 0], expected: null },
    ])('$name gives $expected', ({ importances, expected }) => {
        expect(dominantDriver(importances.map((importance, i) => feature(`f${i}`, importance)))).toEqual(expected)
    })
})
