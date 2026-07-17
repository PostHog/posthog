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
            name: 'not contains',
            conditions: { url: '/pricing', urlMatchType: SurveyMatchType.NotIContains },
            expected: { url: '/pricing', operator: PropertyOperator.NotIContains },
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
            name: 'is not',
            conditions: { url: 'https://example.com/admin', urlMatchType: SurveyMatchType.IsNot },
            expected: { url: 'https://example.com/admin', operator: PropertyOperator.IsNot },
        },
        {
            name: 'valid regex',
            conditions: { url: '^https://example.com/docs/.*', urlMatchType: SurveyMatchType.Regex },
            expected: { url: '^https://example.com/docs/.*', operator: PropertyOperator.Regex },
        },
        {
            name: 'invalid regex',
            conditions: { url: '(unclosed', urlMatchType: SurveyMatchType.Regex },
            expected: null,
        },
        {
            name: 'invalid not-regex',
            conditions: { url: '(unclosed', urlMatchType: SurveyMatchType.NotRegex },
            expected: null,
        },
        {
            name: 'url is trimmed',
            conditions: { url: '  /pricing  ', urlMatchType: SurveyMatchType.Contains },
            expected: { url: '/pricing', operator: PropertyOperator.IContains },
        },
    ])('$name', ({ conditions, expected }) => {
        expect(getUrlAudienceEstimateParams(conditions)).toEqual(expected)
    })
})
