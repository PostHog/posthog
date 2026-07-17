import { PropertyOperator, SurveyMatchType } from '~/types'

import { getUrlAudienceEstimateParams } from './SurveyUrlAudienceEstimate'

describe('getUrlAudienceEstimateParams', () => {
    it.each([
        { name: 'no conditions', conditions: null, expected: null },
        { name: 'empty url', conditions: { url: '' }, expected: null },
        { name: 'whitespace url', conditions: { url: '   ' }, expected: null },
        {
            name: 'default match type falls back to icontains',
            conditions: { url: '/pricing' },
            expected: { url: '/pricing', operator: PropertyOperator.IContains },
        },
        {
            name: 'contains',
            conditions: { url: '/pricing', urlMatchType: SurveyMatchType.Contains },
            expected: { url: '/pricing', operator: PropertyOperator.IContains },
        },
        {
            name: 'exact with a full URL',
            conditions: { url: 'https://example.com/pricing', urlMatchType: SurveyMatchType.Exact },
            expected: { url: 'https://example.com/pricing', operator: PropertyOperator.Exact },
        },
        {
            name: 'exact with a bare path never matches, so no estimate',
            conditions: { url: '/pricing', urlMatchType: SurveyMatchType.Exact },
            expected: null,
        },
        {
            name: 'valid regex',
            conditions: { url: '^https://example.com/docs/.*', urlMatchType: SurveyMatchType.Regex },
            expected: { url: '^https://example.com/docs/.*', operator: PropertyOperator.Regex },
        },
        {
            name: 'regex invalid everywhere',
            conditions: { url: '(unclosed', urlMatchType: SurveyMatchType.Regex },
            expected: null,
        },
        {
            name: 'regex valid in JS but not in RE2 (lookahead) never queries',
            conditions: { url: '^https://example\\.com/(?!admin)', urlMatchType: SurveyMatchType.Regex },
            expected: null,
        },
        {
            name: 'url is trimmed',
            conditions: { url: '  /pricing  ', urlMatchType: SurveyMatchType.Contains },
            expected: { url: '/pricing', operator: PropertyOperator.IContains },
        },
        {
            name: 'negative operators show no estimate: is not',
            conditions: { url: 'https://example.com/admin', urlMatchType: SurveyMatchType.IsNot },
            expected: null,
        },
        {
            name: 'negative operators show no estimate: not contains',
            conditions: { url: '/pricing', urlMatchType: SurveyMatchType.NotIContains },
            expected: null,
        },
        {
            name: 'negative operators show no estimate: not regex',
            conditions: { url: '^https://example.com/docs/.*', urlMatchType: SurveyMatchType.NotRegex },
            expected: null,
        },
    ])('$name', ({ conditions, expected }) => {
        expect(getUrlAudienceEstimateParams(conditions)).toEqual(expected)
    })
})
