import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator, SurveyMatchType } from '~/types'

import { surveyLogic } from './surveyLogic'
import { getUrlAudienceEstimateParams, surveyUrlAudienceEstimateLogic } from './surveyUrlAudienceEstimateLogic'

describe('surveyUrlAudienceEstimateLogic', () => {
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

    describe('estimate loading', () => {
        let logic: ReturnType<typeof surveyUrlAudienceEstimateLogic.build>

        beforeEach(async () => {
            initKeaTests()

            useMocks({
                get: {
                    '/api/projects/:team/surveys/': () => [200, { count: 0, results: [], next: null, previous: null }],
                    '/api/projects/:team/surveys/responses_count/': () => [200, {}],
                },
            })

            logic = surveyUrlAudienceEstimateLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            jest.clearAllMocks()
        })

        it('queries the estimate when the URL condition changes and resets when it is cleared', async () => {
            jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [[42]] } as any)

            await expectLogic(logic, () => {
                surveyLogic({ id: 'new' }).actions.setSurveyValue('conditions', {
                    url: '/pricing',
                    urlMatchType: SurveyMatchType.Contains,
                })
            })
                .toDispatchActions(['refreshUrlAudienceEstimate'])
                .toDispatchActions([
                    logic.actionCreators.setUrlAudienceEstimate({ status: 'loading' }),
                    logic.actionCreators.setUrlAudienceEstimate({ status: 'loaded', count: 42 }),
                ])
                .toMatchValues({ urlAudienceEstimate: { status: 'loaded', count: 42 } })

            expect(api.queryHogQL).toHaveBeenCalledTimes(1)
            expect(api.queryHogQL).toHaveBeenCalledWith(
                expect.stringContaining('uniq(person_id)'),
                expect.objectContaining({ name: 'survey_url_audience_estimate' }),
                expect.objectContaining({
                    queryParams: {
                        filters: {
                            properties: [
                                {
                                    key: '$current_url',
                                    operator: PropertyOperator.IContains,
                                    type: PropertyFilterType.Event,
                                    value: '/pricing',
                                },
                            ],
                        },
                    },
                })
            )

            await expectLogic(logic, () => {
                surveyLogic({ id: 'new' }).actions.setSurveyValue('conditions', { url: '' })
            }).toMatchValues({ urlAudienceEstimate: { status: 'idle' } })

            expect(api.queryHogQL).toHaveBeenCalledTimes(1)
        })

        it('surfaces an error state when the estimate query fails', async () => {
            jest.spyOn(api, 'queryHogQL').mockRejectedValue(new Error('query failed'))

            await expectLogic(logic, () => {
                surveyLogic({ id: 'new' }).actions.setSurveyValue('conditions', {
                    url: '/pricing',
                    urlMatchType: SurveyMatchType.Contains,
                })
            }).toDispatchActions([
                logic.actionCreators.setUrlAudienceEstimate({ status: 'loading' }),
                logic.actionCreators.setUrlAudienceEstimate({ status: 'error' }),
            ])
        })
    })
})
