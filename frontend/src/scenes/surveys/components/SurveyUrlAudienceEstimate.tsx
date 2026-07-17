import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { HogQLQueryString } from '~/queries/utils'
import { PropertyFilterType, PropertyOperator, SurveyDisplayConditions, SurveyMatchType } from '~/types'

import { surveyLogic } from '../surveyLogic'

export const URL_AUDIENCE_ESTIMATE_DAYS = 30
const URL_AUDIENCE_ESTIMATE_DEBOUNCE_MS = 500
const URL_AUDIENCE_ESTIMATE_TAGS = {
    scene: 'Survey' as const,
    productKey: 'surveys' as const,
    name: 'survey_url_audience_estimate' as const,
}

// SurveyMatchType members alias PropertyOperator values, but the enums are distinct to TypeScript
const SURVEY_MATCH_TYPE_TO_PROPERTY_OPERATOR: Record<SurveyMatchType, PropertyOperator> = {
    [SurveyMatchType.Exact]: PropertyOperator.Exact,
    [SurveyMatchType.IsNot]: PropertyOperator.IsNot,
    [SurveyMatchType.Contains]: PropertyOperator.IContains,
    [SurveyMatchType.NotIContains]: PropertyOperator.NotIContains,
    [SurveyMatchType.Regex]: PropertyOperator.Regex,
    [SurveyMatchType.NotRegex]: PropertyOperator.NotRegex,
}

type UrlAudienceEstimate =
    | { status: 'idle' }
    | { status: 'loading' }
    | { status: 'loaded'; count: number }
    | { status: 'error' }

export function getUrlAudienceEstimateParams(
    conditions: Pick<SurveyDisplayConditions, 'url' | 'urlMatchType'> | null | undefined
): { url: string; operator: PropertyOperator } | null {
    const url = conditions?.url?.trim()
    if (!url) {
        return null
    }
    const matchType = conditions?.urlMatchType || SurveyMatchType.Contains
    // $current_url always includes protocol and host, so an exact match against a bare path never matches
    if (matchType === SurveyMatchType.Exact && url.startsWith('/')) {
        return null
    }
    if (matchType === SurveyMatchType.Regex || matchType === SurveyMatchType.NotRegex) {
        try {
            new RegExp(url)
        } catch {
            return null
        }
    }
    return { url, operator: SURVEY_MATCH_TYPE_TO_PROPERTY_OPERATOR[matchType] }
}

/** Estimated unique users who viewed pages matching the survey's URL condition in the last
 * {@link URL_AUDIENCE_ESTIMATE_DAYS} days. Render it only on editing surfaces, within a `BindLogic`
 * for `surveyLogic` — rendering it is what triggers the estimate queries. */
export function SurveyUrlAudienceEstimate({ className }: { className?: string }): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const [estimate, setEstimate] = useState<UrlAudienceEstimate>({ status: 'idle' })

    const params = getUrlAudienceEstimateParams(survey.conditions)
    const url = params?.url
    const operator = params?.operator

    useEffect(() => {
        if (!url || !operator) {
            setEstimate({ status: 'idle' })
            return
        }

        const abortController = new AbortController()
        const timeout = window.setTimeout(async () => {
            setEstimate({ status: 'loading' })

            try {
                const query = `
                    SELECT uniq(person_id)
                    FROM events
                    WHERE event = '$pageview'
                        AND timestamp >= now() - INTERVAL ${URL_AUDIENCE_ESTIMATE_DAYS} DAY
                        AND {filters}
                ` as HogQLQueryString

                const response = await api.queryHogQL<[[number]]>(query, URL_AUDIENCE_ESTIMATE_TAGS, {
                    requestOptions: { signal: abortController.signal },
                    queryParams: {
                        filters: {
                            properties: [
                                {
                                    key: '$current_url',
                                    operator,
                                    type: PropertyFilterType.Event,
                                    value: url,
                                },
                            ],
                        },
                    },
                })

                setEstimate({ status: 'loaded', count: response.results?.[0]?.[0] ?? 0 })
            } catch (error) {
                if ((error as { name?: string }).name !== 'AbortError') {
                    setEstimate({ status: 'error' })
                }
            }
        }, URL_AUDIENCE_ESTIMATE_DEBOUNCE_MS)

        return () => {
            window.clearTimeout(timeout)
            abortController.abort()
        }
    }, [url, operator])

    if (estimate.status === 'idle') {
        return null
    }

    if (estimate.status === 'loading') {
        return (
            <p className={cn('text-xs text-muted flex items-center gap-1', className)}>
                <Spinner className="text-xs" /> Estimating matching users...
            </p>
        )
    }

    if (estimate.status === 'error') {
        return (
            <p className={cn('text-xs text-muted', className)}>
                Unable to estimate matching users for this URL condition.
            </p>
        )
    }

    return (
        <p className={cn('text-xs text-muted', className)}>
            About {humanFriendlyNumber(estimate.count)} unique {estimate.count === 1 ? 'user' : 'users'} viewed matching
            URLs in the last {URL_AUDIENCE_ESTIMATE_DAYS} days.
        </p>
    )
}
