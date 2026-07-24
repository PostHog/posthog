import { useValues } from 'kea'
import { RE2JS } from 're2js'
import { useEffect, useState } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { cn } from 'lib/utils/css-classes'
import { uuid } from 'lib/utils/dom'
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

// Positive match types only: an estimate for a negative condition ("doesn't contain ...") counts
// nearly everyone, which costs a full scan for a number that misleads more than it informs.
// SurveyMatchType members alias PropertyOperator values, but the enums are distinct to TypeScript.
const SURVEY_MATCH_TYPE_TO_PROPERTY_OPERATOR: Partial<Record<SurveyMatchType, PropertyOperator>> = {
    [SurveyMatchType.Exact]: PropertyOperator.Exact,
    [SurveyMatchType.Contains]: PropertyOperator.IContains,
    [SurveyMatchType.Regex]: PropertyOperator.Regex,
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
    const operator = SURVEY_MATCH_TYPE_TO_PROPERTY_OPERATOR[matchType]
    if (!operator) {
        return null
    }
    // $current_url always includes protocol and host, so an exact match against a bare path never matches
    if (matchType === SurveyMatchType.Exact && url.startsWith('/')) {
        return null
    }
    if (matchType === SurveyMatchType.Regex) {
        // The estimate runs in ClickHouse, which evaluates RE2 — JS-only syntax (e.g. lookaheads)
        // can be a valid survey condition yet would only ever produce a failing query here
        try {
            RE2JS.compile(url)
        } catch {
            return null
        }
    }
    return { url, operator }
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

        // Show progress immediately so a stale count never lingers through the debounce window
        setEstimate({ status: 'loading' })

        const abortController = new AbortController()
        const clientQueryId = uuid()
        let queryInFlight = false
        const timeout = window.setTimeout(async () => {
            try {
                const query = `
                    SELECT uniq(person_id)
                    FROM events
                    WHERE event = '$pageview'
                        AND timestamp >= now() - INTERVAL ${URL_AUDIENCE_ESTIMATE_DAYS} DAY
                        AND {filters}
                ` as HogQLQueryString

                queryInFlight = true
                const response = await api.queryHogQL<[[number]]>(query, URL_AUDIENCE_ESTIMATE_TAGS, {
                    clientQueryId,
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
                queryInFlight = false

                const count = response.results?.[0]?.[0]
                setEstimate(typeof count === 'number' ? { status: 'loaded', count } : { status: 'error' })
            } catch (error) {
                queryInFlight = false
                if ((error as { name?: string }).name !== 'AbortError') {
                    setEstimate({ status: 'error' })
                }
            }
        }, URL_AUDIENCE_ESTIMATE_DEBOUNCE_MS)

        return () => {
            window.clearTimeout(timeout)
            abortController.abort()
            if (queryInFlight) {
                // Aborting only drops the connection — also cancel the ClickHouse query server-side
                void api.insights.cancelQuery(clientQueryId)
            }
        }
    }, [url, operator])

    if (estimate.status === 'idle') {
        return null
    }

    let content: JSX.Element
    if (estimate.status === 'loading') {
        content = (
            <p className={cn('text-xs text-muted flex items-center gap-1', className)}>
                <Spinner className="text-xs" /> Estimating matching users...
            </p>
        )
    } else if (estimate.status === 'error') {
        content = (
            <p className={cn('text-xs text-muted', className)}>
                Unable to estimate matching users for this URL condition.
            </p>
        )
    } else if (estimate.count === 0) {
        content = (
            <p className={cn('text-xs text-muted', className)}>
                No pageviews matched this URL condition in the last {URL_AUDIENCE_ESTIMATE_DAYS} days. Double-check the
                pattern if you expected matches.
            </p>
        )
    } else {
        content = (
            <p className={cn('text-xs text-muted', className)}>
                About {humanFriendlyNumber(estimate.count)} unique {estimate.count === 1 ? 'user' : 'users'} viewed
                matching URLs in the last {URL_AUDIENCE_ESTIMATE_DAYS} days.
            </p>
        )
    }

    return <div aria-live="polite">{content}</div>
}
