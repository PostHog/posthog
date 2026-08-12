import { urls } from 'scenes/urls'

import { getEvaluationBackTarget, getEvaluationTemplateSelectionUrl } from './evaluationNavigation'

describe('evaluation navigation', () => {
    it.each([
        ['blank', undefined, {}],
        ['Hog', 'cost_latency', { template: 'cost_latency' }],
    ])('builds a clean %s template selection URL', (_name, templateKey, expectedTemplateParams) => {
        const url = new URL(
            getEvaluationTemplateSelectionUrl(
                {
                    tab: 'settings',
                    template: 'sentiment',
                    type: 'sentiment',
                    returnTo: urls.aiObservabilitySentiment(),
                },
                templateKey
            ),
            'https://posthog.test'
        )

        expect(url.pathname).toBe(urls.aiObservabilityEvaluation('new'))
        expect(Object.fromEntries(url.searchParams)).toEqual({
            tab: 'settings',
            ...expectedTemplateParams,
            returnTo: urls.aiObservabilityEvaluationTemplates(),
        })
    })

    it.each([
        [
            'template picker',
            true,
            { template: 'cost_latency', type: 'sentiment', tab: 'settings' },
            'Templates',
            `${urls.aiObservabilityEvaluationTemplates()}?tab=settings`,
        ],
        [
            'sentiment tab',
            true,
            { type: 'sentiment', returnTo: urls.aiObservabilitySentiment() },
            'Sentiment',
            urls.aiObservabilitySentiment(),
        ],
        [
            'trace',
            true,
            { type: 'sentiment', returnTo: urls.aiObservabilityTrace('trace-id') },
            'Trace',
            urls.aiObservabilityTrace('trace-id'),
        ],
        [
            'evaluation list',
            false,
            { template: 'sentiment', type: 'sentiment', tab: 'settings' },
            'Evaluations',
            `${urls.aiObservabilityEvaluations()}?tab=settings`,
        ],
    ])('returns a draft opened from the %s to its origin', (_origin, isNew, searchParams, name, path) => {
        expect(getEvaluationBackTarget(isNew, searchParams)).toMatchObject({ name, path })
    })
})
