import posthog from 'posthog-js'
import { useEffect, useMemo, useState } from 'react'

import api from 'lib/api'

import { Survey } from '~/types'

/**
 * Fetch all insight IDs which are already linked to surveys. This is separate
 * from surveysLogic to avoid side effects (e.g. product intent) in unrelated
 * components, like dashboards
 *
 * @returns set of insight IDs already linked to existing surveys
 */
export function useSurveyLinkedInsights({ skip }: { skip?: boolean }): {
    loading: boolean
    data: Set<number>
} {
    const [surveys, setSurveys] = useState<Survey[]>([])
    const [loading, setLoading] = useState<boolean>(true)

    useEffect(() => {
        if (skip) {
            return
        }
        api.surveys
            .list()
            .then((response) => setSurveys(response.results))
            .catch((error) => {
                posthog.captureException(error, {
                    action: 'fetch-survey-linked-insights',
                })
            })
            .finally(() => setLoading(false))
    }, [skip])

    return {
        loading,
        data: useMemo(
            () => new Set(surveys.map((survey) => survey.linked_insight_id).filter((id): id is number => id != null)),
            [surveys]
        ),
    }
}
