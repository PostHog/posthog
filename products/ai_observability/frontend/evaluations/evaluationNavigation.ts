import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

export interface EvaluationBackTarget {
    name: 'Evaluations' | 'Templates' | 'Sentiment' | 'Trace'
    path: string
    key: string
    iconType: 'llm_evaluations' | 'llm_analytics'
}

function searchParamsWithoutEvaluationSource(searchParams: Record<string, any>): Record<string, any> {
    const { returnTo: _returnTo, template: _template, type: _type, ...remainingSearchParams } = searchParams
    return remainingSearchParams
}

function targetFromReturnTo(returnTo: unknown): EvaluationBackTarget | null {
    if (returnTo === urls.aiObservabilityEvaluationTemplates()) {
        return {
            name: 'Templates',
            path: returnTo,
            key: 'AIObservabilityEvaluationTemplates',
            iconType: 'llm_evaluations',
        }
    }

    if (returnTo === urls.aiObservabilitySentiment()) {
        return {
            name: 'Sentiment',
            path: returnTo,
            key: 'AIObservabilitySentiment',
            iconType: 'llm_analytics',
        }
    }

    if (typeof returnTo === 'string' && returnTo.startsWith(`${urls.aiObservabilityTraces()}/`)) {
        return {
            name: 'Trace',
            path: returnTo,
            key: 'AIObservabilityTrace',
            iconType: 'llm_analytics',
        }
    }

    return null
}

export function getEvaluationBackTarget(
    isNewEvaluation: boolean,
    searchParams: Record<string, any>
): EvaluationBackTarget {
    const remainingSearchParams = searchParamsWithoutEvaluationSource(searchParams)
    const evaluationsTarget: EvaluationBackTarget = {
        name: 'Evaluations',
        path: combineUrl(urls.aiObservabilityEvaluations(), remainingSearchParams).url,
        key: 'AIObservabilityEvaluations',
        iconType: 'llm_evaluations',
    }

    if (!isNewEvaluation) {
        return evaluationsTarget
    }

    const returnToTarget = targetFromReturnTo(searchParams.returnTo)
    if (returnToTarget) {
        return returnToTarget
    }

    if (typeof searchParams.template === 'string') {
        return {
            name: 'Templates',
            path: combineUrl(urls.aiObservabilityEvaluationTemplates(), remainingSearchParams).url,
            key: 'AIObservabilityEvaluationTemplates',
            iconType: 'llm_evaluations',
        }
    }

    return evaluationsTarget
}

export function getEvaluationTemplateSelectionUrl(searchParams: Record<string, any>, templateKey?: string): string {
    return combineUrl(urls.aiObservabilityEvaluation('new'), {
        ...searchParamsWithoutEvaluationSource(searchParams),
        ...(templateKey ? { template: templateKey } : {}),
        returnTo: urls.aiObservabilityEvaluationTemplates(),
    }).url
}
